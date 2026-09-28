"""User profile DTOs — data shapes ported from the frontend model.

Throwaway mock DTOs for profile data. Data shapes only — no logic, no
validation, no domain behavior. Mirrors the frontend
`user-profile-dto.model.ts`. Intended to be deleted later.

Each persona block is optional so any persona can be modelled in isolation.
Catalog FK fields (``*_id`` / ``*_ids``) reference backend catalogs that are
still pending.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Literal

from api.common.errors.validationError import ValidationError
from api.common.valueObjects.email import Email
from api.member.fullName import FullName

# ──── Shared types ────────────────────────────────────────────────────────────

# Athlete level. Req 8.2
ProfileAthleteLevel = Literal["amateur", "elite", "professional"]

UserStatus = Literal[
    "active", "inactive", "suspended", "pending_confirmation", "pending_tenant"
]

RegistrationType = Literal["native", "social"]

_VALID_STATUSES: set[str] = {
    "active",
    "inactive",
    "suspended",
    "pending_confirmation",
    "pending_tenant",
}

_VALID_REGISTRATION_TYPES: set[str] = {"native", "social"}


@dataclass
class ProfileAttachment:
    """A single uploaded file/document (ID photo, diploma, certificate, ...). Req 4."""

    file_name: str
    url: str  # reference to the stored file
    mime_type: str | None = None  # pending: attachment metadata not finalized


# ──── User entity. Req 5 ────────────────────────────────────────────────────────


class User:
    """Domain entity representing a system user.

    Users authenticate via Cognito and can belong to multiple tenants. The User
    record is independent of tenant membership. This entity also carries the
    common profile block (identity, contact, and marketplace visibility data)
    that describes the person behind the account. Req 5.
    """

    __slots__ = (
        # ── Cognito / account identity ──
        "_user_id",
        "_email",
        "_cognito_sub",
        "_full_name",
        "_default_tenant_id",
        "_status",
        "_registration_type",
        "_created_at",
        "_updated_at",
        # ── Common profile block. Req 5 ──
        "_profile_photo",
        "_first_name",
        "_last_name",
        "_birth_date",
        "_identity_document_number",
        "_document_type_id",
        "_id_card_verification",
        "_nationality_id",
        "_sex_id",
        "_person_type_id",
        "_visible_in_marketplace",
        "_address",
        "_postal_code",
        "_city",
        "_province",
        "_country",
        "_phone",
    )

    _user_id: str
    _email: Email
    _cognito_sub: str
    _full_name: FullName
    _default_tenant_id: str | None
    _status: UserStatus
    _registration_type: RegistrationType
    _created_at: datetime
    _updated_at: datetime

    # Common profile block. Req 5
    _profile_photo: ProfileAttachment | None
    _first_name: str | None
    _last_name: str | None
    _birth_date: date | None  # Req 5.3
    _identity_document_number: str | None
    _document_type_id: str | None  # Catalog FK — pending "document type" catalog. Req 3.2
    _id_card_verification: ProfileAttachment | None  # verification photo. Req 4.2
    _nationality_id: str | None  # Catalog FK — pending "nationality" catalog
    _sex_id: str | None  # Catalog FK — pending "sex" catalog
    _person_type_id: str | None  # Catalog FK — pending "person type" catalog
    _visible_in_marketplace: bool | None  # marketplace visibility. Req 5.4
    _address: str | None
    _postal_code: str | None
    _city: str | None
    _province: str | None
    _country: str | None
    _phone: str | None

    def __init__(
        self,
        user_id: str,
        email: Email,
        cognito_sub: str,
        full_name: FullName,
        status: UserStatus,
        created_at: datetime,
        updated_at: datetime,
        default_tenant_id: str | None = None,
        registration_type: RegistrationType = "native",
        *,
        profile_photo: ProfileAttachment | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        birth_date: date | None = None,
        identity_document_number: str | None = None,
        document_type_id: str | None = None,
        id_card_verification: ProfileAttachment | None = None,
        nationality_id: str | None = None,
        sex_id: str | None = None,
        person_type_id: str | None = None,
        visible_in_marketplace: bool | None = None,
        address: str | None = None,
        postal_code: str | None = None,
        city: str | None = None,
        province: str | None = None,
        country: str | None = None,
        phone: str | None = None,
    ) -> None:
        object.__setattr__(self, "_user_id", user_id)
        object.__setattr__(self, "_email", email)
        object.__setattr__(self, "_cognito_sub", cognito_sub)
        object.__setattr__(self, "_full_name", full_name)
        object.__setattr__(self, "_default_tenant_id", default_tenant_id)
        object.__setattr__(self, "_status", status)
        object.__setattr__(self, "_registration_type", registration_type)
        object.__setattr__(self, "_created_at", created_at)
        object.__setattr__(self, "_updated_at", updated_at)
        # Common profile block. Req 5
        object.__setattr__(self, "_profile_photo", profile_photo)
        object.__setattr__(self, "_first_name", first_name)
        object.__setattr__(self, "_last_name", last_name)
        object.__setattr__(self, "_birth_date", birth_date)
        object.__setattr__(
            self, "_identity_document_number", identity_document_number
        )
        object.__setattr__(self, "_document_type_id", document_type_id)
        object.__setattr__(self, "_id_card_verification", id_card_verification)
        object.__setattr__(self, "_nationality_id", nationality_id)
        object.__setattr__(self, "_sex_id", sex_id)
        object.__setattr__(self, "_person_type_id", person_type_id)
        object.__setattr__(self, "_visible_in_marketplace", visible_in_marketplace)
        object.__setattr__(self, "_address", address)
        object.__setattr__(self, "_postal_code", postal_code)
        object.__setattr__(self, "_city", city)
        object.__setattr__(self, "_province", province)
        object.__setattr__(self, "_country", country)
        object.__setattr__(self, "_phone", phone)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(f"Cannot modify immutable {type(self).__name__}")

    def __delattr__(self, name: str) -> None:
        raise AttributeError(f"Cannot modify immutable {type(self).__name__}")

    # ──── Properties ──────────────────────────────────────────────────────────

    @property
    def user_id(self) -> str:
        return self._user_id

    @property
    def email(self) -> Email:
        return self._email

    @property
    def cognito_sub(self) -> str:
        return self._cognito_sub

    @property
    def full_name(self) -> FullName:
        return self._full_name

    @property
    def default_tenant_id(self) -> str | None:
        """The user's default (active) tenant, resolved per-request after login.

        May be None until the user is associated with a tenant. The access token
        is tenant-agnostic; the AuthGuard resolves the active tenant from this value.
        """
        return self._default_tenant_id

    @property
    def status(self) -> UserStatus:
        return self._status

    @property
    def registration_type(self) -> RegistrationType:
        """How the user registered: "native" (email/password) or "social" (federated)."""
        return self._registration_type

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        return self._updated_at

    # ── Common profile block properties. Req 5 ──

    @property
    def profile_photo(self) -> ProfileAttachment | None:
        return self._profile_photo

    @property
    def first_name(self) -> str | None:
        return self._first_name

    @property
    def last_name(self) -> str | None:
        return self._last_name

    @property
    def birth_date(self) -> date | None:
        return self._birth_date

    @property
    def identity_document_number(self) -> str | None:
        return self._identity_document_number

    @property
    def document_type_id(self) -> str | None:
        return self._document_type_id

    @property
    def id_card_verification(self) -> ProfileAttachment | None:
        return self._id_card_verification

    @property
    def nationality_id(self) -> str | None:
        return self._nationality_id

    @property
    def sex_id(self) -> str | None:
        return self._sex_id

    @property
    def person_type_id(self) -> str | None:
        return self._person_type_id

    @property
    def visible_in_marketplace(self) -> bool | None:
        return self._visible_in_marketplace

    @property
    def address(self) -> str | None:
        return self._address

    @property
    def postal_code(self) -> str | None:
        return self._postal_code

    @property
    def city(self) -> str | None:
        return self._city

    @property
    def province(self) -> str | None:
        return self._province

    @property
    def country(self) -> str | None:
        return self._country

    @property
    def phone(self) -> str | None:
        return self._phone

    # ──── Factory Methods ─────────────────────────────────────────────────────

    @staticmethod
    def create(
        email: str,
        cognito_sub: str,
        full_name: str,
        status: str = "active",
        default_tenant_id: str | None = None,
        registration_type: str = "native",
    ) -> User:
        """Create a new User with generated user_id and timestamps.

        Args:
            email: Raw email string (will be validated).
            cognito_sub: The Cognito user sub identifier.
            full_name: Raw full name string (will be validated).
            status: Initial status. Defaults to "active".
            default_tenant_id: The user's default (active) tenant, if known at
                creation time (e.g. the tenant they self-register into). Optional.
            registration_type: How the user registered — "native" (email/password)
                or "social" (federated). Defaults to "native".

        Returns:
            A validated User entity.

        Raises:
            ValidationError: If email, full_name, status, or registration_type is invalid.
        """
        validated_email = Email.create(email)
        validated_full_name = FullName.create(full_name)

        if status not in _VALID_STATUSES:
            raise ValidationError(
                f"Invalid user status: '{status}'. Must be one of: {', '.join(sorted(_VALID_STATUSES))}",
                field="status",
            )

        if registration_type not in _VALID_REGISTRATION_TYPES:
            raise ValidationError(
                f"Invalid registration type: '{registration_type}'. "
                f"Must be one of: {', '.join(sorted(_VALID_REGISTRATION_TYPES))}",
                field="registration_type",
            )

        now = datetime.now(timezone.utc)

        return User(
            user_id=str(uuid.uuid4()),
            email=validated_email,
            cognito_sub=cognito_sub,
            full_name=validated_full_name,
            status=status,  # type: ignore[arg-type]
            created_at=now,
            updated_at=now,
            default_tenant_id=default_tenant_id,
            registration_type=registration_type,  # type: ignore[arg-type]
        )

    @staticmethod
    def reconstitute(
        user_id: str,
        email: str,
        cognito_sub: str,
        full_name: str,
        status: str,
        created_at: datetime,
        updated_at: datetime,
        default_tenant_id: str | None = None,
        registration_type: str = "native",
    ) -> User:
        """Reconstitute a User from persisted data (no validation of format).

        Used by repository mappers to rebuild entities from the data store.

        Args:
            user_id: Existing user UUID.
            email: Stored email value.
            cognito_sub: Stored Cognito sub.
            full_name: Stored full name.
            status: Stored status string.
            created_at: Original creation timestamp.
            updated_at: Last update timestamp.
            default_tenant_id: Stored default tenant id, if any. Optional.
            registration_type: Stored registration type. Defaults to "native"
                for backward compatibility with records written before social login.

        Returns:
            A User entity reconstituted from stored data.

        Raises:
            ValidationError: If status or registration_type is not a recognized value.
        """
        if status not in _VALID_STATUSES:
            raise ValidationError(
                f"Invalid user status: '{status}'. Must be one of: {', '.join(sorted(_VALID_STATUSES))}",
                field="status",
            )

        if registration_type not in _VALID_REGISTRATION_TYPES:
            raise ValidationError(
                f"Invalid registration type: '{registration_type}'. "
                f"Must be one of: {', '.join(sorted(_VALID_REGISTRATION_TYPES))}",
                field="registration_type",
            )

        return User(
            user_id=user_id,
            email=Email(value=email),
            cognito_sub=cognito_sub,
            full_name=FullName(full_name),
            status=status,  # type: ignore[arg-type]
            created_at=created_at,
            updated_at=updated_at,
            default_tenant_id=default_tenant_id,
            registration_type=registration_type,  # type: ignore[arg-type]
        )

    # ──── Status Transitions ──────────────────────────────────────────────────

    def activate(self) -> User:
        """Transition user to active status.

        Raises:
            ValidationError: If user is already active.
        """
        if self._status == "active":
            raise ValidationError("User is already active", field="status")
        return self._with_status("active")

    def deactivate(self) -> User:
        """Transition user to inactive status.

        Raises:
            ValidationError: If user is already inactive.
        """
        if self._status == "inactive":
            raise ValidationError("User is already inactive", field="status")
        return self._with_status("inactive")

    def suspend(self) -> User:
        """Transition user to suspended status.

        Raises:
            ValidationError: If user is already suspended.
        """
        if self._status == "suspended":
            raise ValidationError("User is already suspended", field="status")
        return self._with_status("suspended")

    def confirm(self) -> User:
        """Transition user from pending_confirmation to active.

        Raises:
            ValidationError: If user is not in pending_confirmation status.
        """
        if self._status != "pending_confirmation":
            raise ValidationError(
                "Only users with 'pending_confirmation' status can be confirmed",
                field="status",
            )
        return self._with_status("active")

    # ──── Internal Helpers ────────────────────────────────────────────────────

    def _with_status(self, new_status: UserStatus) -> User:
        """Return a new User instance with the given status and updated timestamp."""
        return User(
            user_id=self._user_id,
            email=self._email,
            cognito_sub=self._cognito_sub,
            full_name=self._full_name,
            status=new_status,
            created_at=self._created_at,
            updated_at=datetime.now(timezone.utc),
            default_tenant_id=self._default_tenant_id,
            registration_type=self._registration_type,
            profile_photo=self._profile_photo,
            first_name=self._first_name,
            last_name=self._last_name,
            birth_date=self._birth_date,
            identity_document_number=self._identity_document_number,
            document_type_id=self._document_type_id,
            id_card_verification=self._id_card_verification,
            nationality_id=self._nationality_id,
            sex_id=self._sex_id,
            person_type_id=self._person_type_id,
            visible_in_marketplace=self._visible_in_marketplace,
            address=self._address,
            postal_code=self._postal_code,
            city=self._city,
            province=self._province,
            country=self._country,
            phone=self._phone,
        )

    # ──── Domain Queries ──────────────────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        """Check if the user is in active status."""
        return self._status == "active"

    # ──── Equality & Representation ───────────────────────────────────────────

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, User):
            return NotImplemented
        return self._user_id == other._user_id

    def __hash__(self) -> int:
        return hash(self._user_id)

    def __repr__(self) -> str:
        return (
            f"User(user_id={self._user_id!r}, email={self._email!r}, "
            f"status={self._status!r})"
        )


# ──── Natural person block. Req 6 ──────────────────────────────────────────────


@dataclass
class ProfileNaturalPersonBlock:
    sports_practiced: list[str] | None = None
    hobbies: list[str] | None = None
    is_amateur_sports: bool | None = None  # Req 6.2


# ──── Health professional block. Req 7 ─────────────────────────────────────────


@dataclass
class ProfileStudyEntry:
    """One study entry. Req 7.4."""

    # required. Catalog FK — pending backend "study level" catalog. Req 3.2
    study_level_id: str
    graduation_year: int | None = None
    obtained_degree: str | None = None
    average: float | None = None
    degree: ProfileAttachment | None = None


@dataclass
class ProfileLanguageEntry:
    """One language entry. Req 7.5."""

    language: str | None = None
    level: str | None = None
    institution: str | None = None
    graduation_year: int | None = None
    certificate: ProfileAttachment | None = None


@dataclass
class ProfileWorkExperienceEntry:
    """One work-experience entry. Req 7.6."""

    workplace: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    currently_working: bool | None = None
    reference_contact: str | None = None
    position: str | None = None
    additional_details: str | None = None


@dataclass
class ProfileSkillEntry:
    """One skill entry. Req 7.7."""

    skill_type: str | None = None
    additional_details: str | None = None


@dataclass
class ProfileHealthProfessionalBlock:
    is_licensed: bool  # required. Req 7.2

    works_remotely: bool | None = None  # Req 7.2
    # Catalog FK — pending backend "license" catalog; only when is_licensed is true. Req 3.2, 7.3
    license_id: str | None = None
    # Catalog FK — pending backend "profession type" catalog. Req 3.2
    profession_type_id: str | None = None
    study_institution: str | None = None
    graduation_date: date | None = None

    studies: list[ProfileStudyEntry] | None = None
    languages: list[ProfileLanguageEntry] | None = None
    work_experience: list[ProfileWorkExperienceEntry] | None = None
    skills: list[ProfileSkillEntry] | None = None


# ──── Athlete block. Req 8 ─────────────────────────────────────────────────────


@dataclass
class ProfileSportPriorExperienceEntry:
    """One prior-experience entry for a sport. Req 8.3."""

    club: str | None = None
    # Catalog FK[] — sport-dependent; pending backend "position" catalog. Req 3.3, 8.5
    position_ids: list[str] | None = None
    entry_date: date | None = None
    exit_date: date | None = None
    details: str | None = None


@dataclass
class ProfileCompetitionEntry:
    """One competition entry for a sport. Req 8.4."""

    tournament: str | None = None
    year: int | None = None
    tournament_position: str | None = None
    # Catalog FK[] — pending backend "achievement" catalog. Req 3.3
    achievement_ids: list[str] | None = None
    details: str | None = None


@dataclass
class ProfileSportEntry:
    """One sport the athlete practices. Req 8.2."""

    sport_type: str | None = None
    personal_record: str | None = None
    # Catalog FK — sport-dependent; pending backend "category" catalog. Req 8.5
    category_id: str | None = None
    # Catalog FK[] — sport-dependent; pending backend "position" catalog. Req 3.3, 8.5
    natural_position_ids: list[str] | None = None
    level: ProfileAthleteLevel | None = None
    current_club: str | None = None
    entry_date: date | None = None

    prior_experience: list[ProfileSportPriorExperienceEntry] | None = None
    competitions: list[ProfileCompetitionEntry] | None = None


@dataclass
class ProfileAthleteBlock:
    sports: list[ProfileSportEntry] | None = None


# ──── Anatomical / clinical block. Req 9 ───────────────────────────────────────


@dataclass
class ProfileInjuryEntry:
    """One injury entry. pending: shape incomplete. Req 9.1."""

    description: str | None = None  # pending: injury fields not finalized


@dataclass
class ProfileAnatomicalBlock:
    """pending: anatomical/clinical block is incomplete; fields will be added later. Req 9.2."""

    weight: float | None = None
    height: float | None = None
    blood_group: str | None = None
    anthropometry: str | None = None
    # Catalog FK — pending backend "somatotype" catalog. Req 3.2
    somatotype_id: str | None = None
    clinical_history: str | None = None
    injuries: list[ProfileInjuryEntry] | None = None
    medical_restrictions: str | None = None


# ──── Club block. Req 10 ───────────────────────────────────────────────────────


@dataclass
class ProfileDisciplineEntry:
    """One discipline the club offers. Req 10.2."""

    discipline_name: str | None = None
    # Catalog FK[] — pending backend "category" catalog. Req 3.3
    category_ids: list[str] | None = None


@dataclass
class ProfileFacilityEntry:
    """One club facility. Req 10.3."""

    name: str | None = None
    # Catalog FK[] — pending backend "facility type" catalog. Req 3.3
    type_ids: list[str] | None = None
    location: str | None = None
    phone_number: str | None = None
    internal_details: str | None = None  # club-internal visibility only. Req 10.3


@dataclass
class ProfileClubBlock:
    name: str | None = None
    legal_name: str | None = None
    founding_year: int | None = None
    location: str | None = None
    phone: str | None = None
    social_links: list[str] | None = None

    disciplines: list[ProfileDisciplineEntry] | None = None
    facilities: list[ProfileFacilityEntry] | None = None


# ──── Manager block. Req 11 ────────────────────────────────────────────────────


@dataclass
class ProfileRepresentedPlayerEntry:
    """One represented player. Req 11.2."""

    first_name: str | None = None
    last_name: str | None = None
    current_club: str | None = None


@dataclass
class ProfileManagerBlock:
    represented_player_count: int | None = None
    main_discipline: str | None = None
    represented_players: list[ProfileRepresentedPlayerEntry] | None = None


# ──── Tutor block. Req 12 ──────────────────────────────────────────────────────


@dataclass
class ProfileTutorBlock:
    legal_guardian_verification: ProfileAttachment | None = None  # Req 12.1


# ──── Club worker block. Req 13 ────────────────────────────────────────────────


@dataclass
class ProfilePriorJobEntry:
    """One prior job. pending: prior-jobs block is incomplete; fields will be added later. Req 13.2."""

    description: str | None = None  # pending: prior-job fields not finalized


@dataclass
class ProfileClubWorkerBlock:
    first_name: str | None = None
    last_name: str | None = None
    work_area: str | None = None
    position: str | None = None
    work_performed: str | None = None
    contact_number: str | None = None

    prior_jobs: list[ProfilePriorJobEntry] | None = None


# ──── Root ─────────────────────────────────────────────────────────────────────


@dataclass
class UserProfileDto:
    """Single root profile DTO. Each persona block is optional so any persona can
    be modelled in isolation. Req 1.1, 1.2, 14.1.
    """

    id: str  # Entity Id — the profile's own primary identifier. Req 3.1

    common: User | None = None
    natural_person: ProfileNaturalPersonBlock | None = None
    health_professional: ProfileHealthProfessionalBlock | None = None
    athlete: ProfileAthleteBlock | None = None
    anatomical: ProfileAnatomicalBlock | None = None
    club: ProfileClubBlock | None = None
    manager: ProfileManagerBlock | None = None
    tutor: ProfileTutorBlock | None = None
    club_worker: ProfileClubWorkerBlock | None = None
