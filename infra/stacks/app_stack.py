"""Account Management application stack (single region, per environment).

Provisions the full backend for one environment:
- DynamoDB single table (PK/SK + GSI1 + GSI2), matching the repositories.
- Cognito User Pool + app client (RS256 tokens; ASF is a multi-region concern,
  tracked separately).
- Four Lambda functions (auth, registration, account types, members) packaged
  from the existing `src/` tree, each running the corresponding handler.
- A REST API Gateway wiring the documented routes, plus a public GET /health
  used later by Route 53 health checks (multi-region spec).

The Lambdas are configured tenant-agnostic RS256 verification: COGNITO_ISSUERS
and COGNITO_CLIENT_IDS are derived from the User Pool created here. No JWT secret.

TODO (custom domain): the API is exposed via its default execute-api endpoint.
A Route 53 hosted zone + ACM certificate + custom domain is intentionally left
as a TODO and will be added alongside the multi-region work.
"""

from __future__ import annotations

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    SecretValue,
    Stack,
)
from aws_cdk import (
    aws_apigateway as apigw,
)
from aws_cdk import (
    aws_cognito as cognito,
)
from aws_cdk import (
    aws_secretsmanager as secretsmanager,
)
from aws_cdk import (
    aws_dynamodb as dynamodb,
)
from aws_cdk import (
    aws_lambda as lambda_,
)
from aws_cdk import (
    aws_logs as logs,
)
from aws_cdk import (
    aws_sns as sns,
)
from constructs import Construct

from config import EnvConfig
from lambda_assets.api_waf import ApiWaf
from lambda_assets.lambda_bundling import build_backend_code
from lambda_assets.observability import Observability

# Lambda runtime for the Python backend (project requires >=3.11).
_RUNTIME = lambda_.Runtime.PYTHON_3_12


class AccountManagementStack(Stack):
    """The full single-region backend stack for one environment."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: EnvConfig,
        **kwargs: object,
    ) -> None:
        """Build the stack.

        Args:
            scope: The CDK app/scope.
            construct_id: Unique stack id (e.g. "AccountManagement-dev").
            config: Per-environment configuration (dev or prod).
            **kwargs: Forwarded to the base Stack (env, description, ...).
        """
        super().__init__(scope, construct_id, **kwargs)
        self._config = config

        # Build the Lambda deployment asset once (source tree + runtime deps)
        # and share it across all four functions to avoid bundling repeatedly.
        self._backend_code = build_backend_code(_RUNTIME)

        table = self._build_table()
        user_pool, user_pool_client, hosted_ui_domain = self._build_cognito()

        issuer = (
            f"https://cognito-idp.{self.region}.amazonaws.com/{user_pool.user_pool_id}"
        )

        common_env = {
            "TABLE_NAME": table.table_name,
            "REGION": self.region,
            # RS256 allow-lists (multi-region ready; here a single local pool).
            "COGNITO_ISSUERS": issuer,
            "COGNITO_CLIENT_IDS": user_pool_client.user_pool_client_id,
            # Backward-compat singular vars used by the admin (sign-up/initiate-auth) path.
            "COGNITO_USER_POOL_ID": user_pool.user_pool_id,
            "COGNITO_CLIENT_ID": user_pool_client.user_pool_client_id,
            "POWERTOOLS_SERVICE_NAME": f"account-management-{config.name}",
            "LOG_LEVEL": "INFO" if config.name == "prod" else "DEBUG",
        }

        # One Lambda per handler module, mirroring the existing entry points.
        auth_fn = self._build_lambda(
            "AuthFn", "interfaces.http.handlers.auth_handler.handler", common_env
        )
        registration_fn = self._build_lambda(
            "RegistrationFn",
            "interfaces.http.handlers.registration_handler.handler",
            common_env,
        )
        account_type_fn = self._build_lambda(
            "AccountTypeFn",
            "interfaces.http.handlers.account_type_handler.handler",
            common_env,
        )
        member_fn = self._build_lambda(
            "MemberFn", "interfaces.http.handlers.member_handler.handler", common_env
        )

        # Grant DynamoDB access (table + indexes) to every function.
        for fn in (auth_fn, registration_fn, account_type_fn, member_fn):
            table.grant_read_write_data(fn)

        # Grant the Cognito admin operations the backend performs (sign-up,
        # admin create user, initiate auth) to the functions that need them.
        for fn in (auth_fn, registration_fn, member_fn):
            user_pool.grant(
                fn,
                "cognito-idp:AdminInitiateAuth",
                "cognito-idp:AdminCreateUser",
                "cognito-idp:AdminGetUser",
                "cognito-idp:AdminDisableUser",
                "cognito-idp:SignUp",
                "cognito-idp:InitiateAuth",
            )

        # Password-recovery / challenge endpoints served by AuthFn call these
        # client-based Cognito operations (see password-recovery-challenge spec).
        # Only AuthFn needs them, so this grant is separate from the shared loop
        # above (registration_fn / member_fn do NOT require the recovery actions).
        user_pool.grant(
            auth_fn,
            "cognito-idp:ForgotPassword",
            "cognito-idp:ConfirmForgotPassword",
            "cognito-idp:RespondToAuthChallenge",
        )

        # Cognito Post Confirmation trigger Lambda (creates records on confirm).
        # Placeholder logic today; see the handler docstring and TODO.md.
        #
        # IMPORTANT: this function must NOT receive env vars that depend on the
        # User Pool (issuers/client ids/pool id). Doing so would create a
        # dependency cycle UserPool -> PostConfirmationFn -> UserPool (the pool
        # depends on the function via the trigger). The pool id arrives at
        # runtime in the Cognito event, so only table/region/logging are needed.
        post_confirmation_env = {
            "TABLE_NAME": table.table_name,
            "REGION": self.region,
            "POWERTOOLS_SERVICE_NAME": f"account-management-{config.name}",
            "LOG_LEVEL": "INFO" if config.name == "prod" else "DEBUG",
        }
        post_confirmation_fn = self._build_lambda(
            "PostConfirmationFn",
            "interfaces.http.handlers.post_confirmation_handler.handler",
            post_confirmation_env,
        )
        table.grant_read_write_data(post_confirmation_fn)
        user_pool.add_trigger(
            cognito.UserPoolOperation.POST_CONFIRMATION,
            post_confirmation_fn,
        )

        # ── Social login (OAuth) Lambda ──────────────────────────────────
        #
        # The OAuthHandlerFn serves the /auth/social/* routes (authorize,
        # callback, select-tenant). It has a *different* environment surface
        # than the main API Lambdas: additionally the Hosted UI domain, the
        # OAuth callback URL, and the HMAC state secret.
        #
        # SOCIAL_STATE_SECRET is sourced from Secrets Manager, never a plaintext
        # env var. Referencing `secret_value_from_json(...).unsafe_unwrap()`
        # renders a Secrets Manager dynamic reference
        # ("{{resolve:secretsmanager:social/state:SecretString:state_secret}}")
        # in the synthesized template — the plaintext value never appears in
        # CloudFormation and is only resolved by the Lambda service at deploy.
        state_secret = secretsmanager.Secret.from_secret_name_v2(
            self, "SocialStateSecret", "social/state"
        )
        oauth_env = {
            "TABLE_NAME": table.table_name,
            "REGION": self.region,
            # RS256 allow-lists consumed by AuthGuardMiddleware (select-tenant).
            "COGNITO_ISSUERS": issuer,
            "COGNITO_CLIENT_IDS": user_pool_client.user_pool_client_id,
            # Singular vars used by the admin/Hosted-UI social flow.
            "COGNITO_USER_POOL_ID": user_pool.user_pool_id,
            "COGNITO_CLIENT_ID": user_pool_client.user_pool_client_id,
            "COGNITO_HOSTED_UI_DOMAIN": hosted_ui_domain,
            # The OAuth redirect_uri must match a callback URL registered on the
            # App Client (see _build_cognito). Use the first configured URL.
            "COGNITO_CALLBACK_URL": config.social_callback_urls[0],
            # HMAC state secret — Secrets Manager dynamic reference, not plaintext.
            "SOCIAL_STATE_SECRET": state_secret.secret_value_from_json(
                "state_secret"
            ).unsafe_unwrap(),
            "POWERTOOLS_SERVICE_NAME": f"account-management-{config.name}",
            "LOG_LEVEL": "INFO" if config.name == "prod" else "DEBUG",
        }
        oauth_fn = self._build_lambda(
            "OAuthHandlerFn",
            "interfaces.http.handlers.oauth_handler.handler",
            oauth_env,
        )
        # DynamoDB access (provisioning users/members/memberships/roles).
        table.grant_read_write_data(oauth_fn)
        # Cognito admin operations the social callback performs: link the
        # federated provider to the destination user and update attributes.
        user_pool.grant(
            oauth_fn,
            "cognito-idp:AdminLinkProviderForUser",
            "cognito-idp:AdminUpdateUserAttributes",
            "cognito-idp:AdminGetUser",
        )
        # Read the HMAC state secret at runtime.
        state_secret.grant_read(oauth_fn)

        api = self._build_api(
            auth_fn=auth_fn,
            registration_fn=registration_fn,
            account_type_fn=account_type_fn,
            member_fn=member_fn,
            oauth_fn=oauth_fn,
        )

        # WAF edge protection (managed rules + per-IP rate limiting) on the API
        # stage. The association is stage-level, so the /auth/social/* routes
        # added in _build_api are covered by the same WAF as every other
        # endpoint via this single association (Req 8.3).
        ApiWaf(
            self,
            "ApiWaf",
            env_name=config.name,
            api=api,
            rate_limit_per_5min=config.waf_rate_limit_per_5min,
        )

        # CloudWatch alarms + SNS topic covering Lambdas, API and DynamoDB.
        observability = Observability(
            self,
            "Observability",
            env_name=config.name,
            functions={
                "auth": auth_fn,
                "registration": registration_fn,
                "accountType": account_type_fn,
                "member": member_fn,
                "postConfirmation": post_confirmation_fn,
                "oauth": oauth_fn,
            },
            api=api,
            table=table,
        )

        self._outputs(
            api, table, user_pool, user_pool_client, issuer, observability.topic
        )

    # ── DynamoDB ──────────────────────────────────────────────────────────────

    def _build_table(self) -> dynamodb.Table:
        """Create the single table with GSI1 and GSI2, matching the repositories."""
        cfg = self._config
        table = dynamodb.Table(
            self,
            "Table",
            table_name=cfg.table_name,
            partition_key=dynamodb.Attribute(
                name="PK", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="SK", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=cfg.point_in_time_recovery,
            ),
            removal_policy=(
                RemovalPolicy.DESTROY
                if cfg.removal_policy_destroy
                else RemovalPolicy.RETAIN
            ),
        )
        # GSI1 and GSI2 are used by the user/member/account-type repositories.
        table.add_global_secondary_index(
            index_name="GSI1",
            partition_key=dynamodb.Attribute(
                name="GSI1PK", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="GSI1SK", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )
        table.add_global_secondary_index(
            index_name="GSI2",
            partition_key=dynamodb.Attribute(
                name="GSI2PK", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="GSI2SK", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )
        return table

    # ── Cognito ─────────────────────────────────────────────────────────────

    def _build_cognito(
        self,
    ) -> tuple[cognito.UserPool, cognito.UserPoolClient, str]:
        """Create the User Pool and app client used for auth (RS256 tokens).

        Returns:
            A tuple of ``(user_pool, user_pool_client, hosted_ui_domain)`` where
            ``hosted_ui_domain`` is the fully-qualified Cognito Hosted UI host
            (e.g. ``sport-dev.auth.sa-east-1.amazoncognito.com``) used by the
            social-login authorize/token endpoints.
        """
        cfg = self._config
        user_pool = cognito.UserPool(
            self,
            "UserPool",
            user_pool_name=f"sport-account-management-{cfg.name}",
            self_sign_up_enabled=True,
            sign_in_aliases=cognito.SignInAliases(email=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=False),
                fullname=cognito.StandardAttribute(required=False, mutable=True),
            ),
            custom_attributes={
                # Stored during sign-up so the Post Confirmation trigger can
                # create DynamoDB records without a separate lookup.
                "tenant_id": cognito.StringAttribute(mutable=False),
                "account_type": cognito.StringAttribute(mutable=True),
                # Social login: the provider subject identifier (Google `sub`
                # / Facebook `id`) and which provider was last used. Mutable so
                # a Native_User can later link a social provider.
                "social_sub": cognito.StringAttribute(mutable=True),
                "provider": cognito.StringAttribute(mutable=True),
            },
            password_policy=cognito.PasswordPolicy(
                min_length=8,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
            ),
            removal_policy=(
                RemovalPolicy.DESTROY
                if cfg.removal_policy_destroy
                else RemovalPolicy.RETAIN
            ),
        )
        # Social Identity Providers (Google + Facebook). Credentials live in
        # AWS Secrets Manager (never hardcoded / never in plaintext env vars);
        # each secret stores a JSON document with `client_id` and
        # `client_secret` fields.
        google_secret = secretsmanager.Secret.from_secret_name_v2(
            self, "GoogleSocialSecret", "social/google"
        )
        facebook_secret = secretsmanager.Secret.from_secret_name_v2(
            self, "FacebookSocialSecret", "social/facebook"
        )

        google_idp = cognito.UserPoolIdentityProviderGoogle(
            self,
            "GoogleIdp",
            user_pool=user_pool,
            client_id=google_secret.secret_value_from_json(
                "client_id"
            ).unsafe_unwrap(),
            client_secret_value=google_secret.secret_value_from_json(
                "client_secret"
            ),
            scopes=["openid", "email", "profile"],
            attribute_mapping=cognito.AttributeMapping(
                email=cognito.ProviderAttribute.GOOGLE_EMAIL,
                fullname=cognito.ProviderAttribute.GOOGLE_NAME,
                custom={
                    # Google's OpenID subject identifier ("sub") is not a
                    # pre-defined ProviderAttribute, so reference it directly.
                    "custom:social_sub": cognito.ProviderAttribute.other("sub"),
                },
            ),
        )

        facebook_idp = cognito.UserPoolIdentityProviderFacebook(
            self,
            "FacebookIdp",
            user_pool=user_pool,
            client_id=facebook_secret.secret_value_from_json(
                "client_id"
            ).unsafe_unwrap(),
            client_secret=facebook_secret.secret_value_from_json(
                "client_secret"
            ).unsafe_unwrap(),
            scopes=["email", "public_profile"],
            attribute_mapping=cognito.AttributeMapping(
                email=cognito.ProviderAttribute.FACEBOOK_EMAIL,
                fullname=cognito.ProviderAttribute.FACEBOOK_NAME,
                custom={
                    "custom:social_sub": cognito.ProviderAttribute.FACEBOOK_ID,
                },
            ),
        )

        user_pool_client = user_pool.add_client(
            "AppClient",
            user_pool_client_name=f"sport-app-client-{cfg.name}",
            # Preserve the existing email+password auth flows used by the
            # native login path; the OAuth Authorization Code Grant below is
            # additive for the social (Hosted UI) flow.
            auth_flows=cognito.AuthFlow(
                user_password=True,
                admin_user_password=True,
            ),
            # Social login: allow the native Cognito directory plus the two
            # federated IDPs created above. Cognito requires every provider a
            # client may use to be listed here explicitly.
            supported_identity_providers=[
                cognito.UserPoolClientIdentityProvider.COGNITO,
                cognito.UserPoolClientIdentityProvider.GOOGLE,
                cognito.UserPoolClientIdentityProvider.FACEBOOK,
            ],
            # Authorization Code Grant is the only flow enabled for the Hosted
            # UI (no implicit grant). Scopes cover OpenID Connect identity plus
            # the email/profile claims the provisioning flow reads.
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.EMAIL,
                    cognito.OAuthScope.PROFILE,
                ],
                # Per-environment URLs come from EnvConfig (config-driven, not
                # hardcoded) so dev and prod register their own destinations.
                # The callback URL(s) point at the app's /auth/social/callback.
                callback_urls=list(cfg.social_callback_urls),
                logout_urls=list(cfg.social_logout_urls),
            ),
            access_token_validity=Duration.hours(1),
            id_token_validity=Duration.hours(1),
            refresh_token_validity=Duration.days(7),
            prevent_user_existence_errors=True,
        )
        # The IDPs must be created before the App Client so that the
        # `supported_identity_providers` above resolve to existing providers.
        # Declaring the dependency here guarantees the correct CloudFormation
        # ordering.
        user_pool_client.node.add_dependency(google_idp)
        user_pool_client.node.add_dependency(facebook_idp)

        # Cognito Hosted UI domain. The prefix must be globally unique within
        # the region; `sport-<env>` keeps dev and prod distinct. This yields
        # https://sport-<env>.auth.<region>.amazoncognito.com used by the
        # authorize/token endpoints of the social flow.
        user_pool.add_domain(
            "HostedUiDomain",
            cognito_domain=cognito.CognitoDomainOptions(
                domain_prefix=f"sport-{cfg.name}",
            ),
        )
        # The fully-qualified Hosted UI host used by the OAuth authorize/token
        # endpoints. Derived from the (globally-unique-per-region) prefix and
        # the stack region so it stays consistent with the domain created above.
        hosted_ui_domain = (
            f"sport-{cfg.name}.auth.{self.region}.amazoncognito.com"
        )
        return user_pool, user_pool_client, hosted_ui_domain

    # ── Lambda ─────────────────────────────────────────────────────────────

    def _build_lambda(
        self, construct_id: str, handler: str, environment: dict[str, str]
    ) -> lambda_.Function:
        """Create a Lambda function from the src/ tree for the given handler.

        Args:
            construct_id: Unique construct id within the stack.
            handler: Dotted handler path (module.function) relative to src/.
            environment: Environment variables to inject.

        Returns:
            The configured Lambda function.
        """
        cfg = self._config
        log_group = logs.LogGroup(
            self,
            f"{construct_id}LogGroup",
            retention=_log_retention(cfg.log_retention_days),
            removal_policy=(
                RemovalPolicy.DESTROY
                if cfg.removal_policy_destroy
                else RemovalPolicy.RETAIN
            ),
        )
        return lambda_.Function(
            self,
            construct_id,
            runtime=_RUNTIME,
            handler=handler,
            code=self._backend_code,
            memory_size=cfg.lambda_memory_mb,
            timeout=Duration.seconds(cfg.lambda_timeout_seconds),
            environment=environment,
            log_group=log_group,
        )

    # ── API Gateway ─────────────────────────────────────────────────────────

    def _build_api(
        self,
        *,
        auth_fn: lambda_.Function,
        registration_fn: lambda_.Function,
        account_type_fn: lambda_.Function,
        member_fn: lambda_.Function,
        oauth_fn: lambda_.Function,
    ) -> apigw.RestApi:
        """Create the REST API and wire all documented routes."""
        cfg = self._config
        api = apigw.RestApi(
            self,
            "Api",
            rest_api_name=f"sport-account-management-{cfg.name}",
            deploy_options=apigw.StageOptions(
                stage_name=cfg.name,
                throttling_rate_limit=cfg.api_throttle_rate,
                throttling_burst_limit=cfg.api_throttle_burst,
                logging_level=apigw.MethodLoggingLevel.INFO,
                metrics_enabled=True,
            ),
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=apigw.Cors.ALL_ORIGINS,
                allow_methods=apigw.Cors.ALL_METHODS,
            ),
        )

        auth_integration = apigw.LambdaIntegration(auth_fn)
        registration_integration = apigw.LambdaIntegration(registration_fn)
        account_type_integration = apigw.LambdaIntegration(account_type_fn)
        member_integration = apigw.LambdaIntegration(member_fn)
        oauth_integration = apigw.LambdaIntegration(oauth_fn)

        # GET /health  (no auth) — target for Route 53 health checks later.
        api.root.add_resource("health").add_method(
            "GET",
            apigw.MockIntegration(
                integration_responses=[
                    apigw.IntegrationResponse(
                        status_code="200",
                        response_templates={"application/json": '{"status":"ok"}'},
                    )
                ],
                request_templates={"application/json": '{"statusCode": 200}'},
            ),
            method_responses=[apigw.MethodResponse(status_code="200")],
        )

        # /auth/{login,refresh,logout,register}
        auth = api.root.add_resource("auth")
        auth.add_resource("login").add_method("POST", auth_integration)
        auth.add_resource("refresh").add_method("POST", auth_integration)
        auth.add_resource("logout").add_method("POST", auth_integration)
        auth.add_resource("register").add_method("POST", registration_integration)

        # Password-recovery / challenge endpoints (public, no authorizer —
        # consistent with login/refresh/logout). All three POST routes are
        # served by the same AuthFn LambdaIntegration; see the
        # password-recovery-challenge spec.
        auth.add_resource("forgot-password").add_method("POST", auth_integration)
        auth.add_resource("confirm-forgot-password").add_method(
            "POST", auth_integration
        )
        auth.add_resource("respond-to-challenge").add_method(
            "POST", auth_integration
        )

        # /auth/social/{proxy+}  →  OAuthHandlerFn (authorize, callback,
        # select-tenant). A greedy {proxy+} resource with ANY method lets the
        # single OAuth Lambda route every social sub-path internally.
        social = auth.add_resource("social")
        social_proxy = social.add_resource("{proxy+}")
        social_proxy.add_method("ANY", oauth_integration)

        # /account-types  and  /account-types/{id}
        account_types = api.root.add_resource("account-types")
        account_types.add_method("POST", account_type_integration)
        account_types.add_method("GET", account_type_integration)
        account_type_id = account_types.add_resource("{id}")
        account_type_id.add_method("PUT", account_type_integration)
        account_type_id.add_method("DELETE", account_type_integration)

        # /members  and  /members/{member_id}
        members = api.root.add_resource("members")
        members.add_method("POST", member_integration)
        members.add_method("GET", member_integration)
        member_id = members.add_resource("{member_id}")
        member_id.add_method("PUT", member_integration)
        member_id.add_method("DELETE", member_integration)

        return api

    # ── Outputs ─────────────────────────────────────────────────────────────

    def _outputs(
        self,
        api: apigw.RestApi,
        table: dynamodb.Table,
        user_pool: cognito.UserPool,
        user_pool_client: cognito.UserPoolClient,
        issuer: str,
        alarm_topic: sns.Topic,
    ) -> None:
        """Emit useful stack outputs."""
        CfnOutput(self, "ApiUrl", value=api.url)
        CfnOutput(self, "TableName", value=table.table_name)
        CfnOutput(self, "UserPoolId", value=user_pool.user_pool_id)
        CfnOutput(self, "UserPoolClientId", value=user_pool_client.user_pool_client_id)
        CfnOutput(self, "CognitoIssuer", value=issuer)
        CfnOutput(self, "AlarmTopicArn", value=alarm_topic.topic_arn)


def _log_retention(days: int) -> logs.RetentionDays:
    """Map a day count to the closest CloudWatch RetentionDays enum value."""
    mapping = {
        1: logs.RetentionDays.ONE_DAY,
        3: logs.RetentionDays.THREE_DAYS,
        5: logs.RetentionDays.FIVE_DAYS,
        7: logs.RetentionDays.ONE_WEEK,
        14: logs.RetentionDays.TWO_WEEKS,
        30: logs.RetentionDays.ONE_MONTH,
        60: logs.RetentionDays.TWO_MONTHS,
        90: logs.RetentionDays.THREE_MONTHS,
    }
    return mapping.get(days, logs.RetentionDays.ONE_MONTH)










