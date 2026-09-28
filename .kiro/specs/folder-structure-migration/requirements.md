# Requirements Document

## Introduction

The Sport_be backend is currently organized as a layered / hexagonal (Clean Architecture) codebase under `src/`, split into technical layers: `domain`, `application`, `infrastructure`, and `interfaces`. Each layer contains sub-folders per business area (`account_type`, `auth`, `member`, `registration`, plus cross-cutting `social_login`/`oauth`, `tenant`, `user`). Naming follows Python `snake_case`.

The reference project `apser-backend-ia-template` uses a **feature-module** architecture: a `python/` root code folder containing `api/<feature>/` self-contained feature modules (flat files named `<feature>Controller.py`, `<feature>Service.py`, `<feature>VM.py`, plus domain model files), a shared `api/common/` module, `lambdas/` entry points, and `tests/<feature>/` mirroring the feature layout. Naming follows `camelCase`.

This feature reorganizes the Sport_be source tree so its folder structure and naming follow the reference project's feature-module convention, **migrating all existing code from the layered structure into feature modules while preserving current runtime behavior** (all imports resolved, deployment handler wiring intact, and the full test suite passing). This is a structural refactoring: no business logic, API contracts, or Lambda entry-point behavior may change.

The migration must accommodate two facts about Sport_be that differ from the reference: (1) Sport_be is deployed as AWS Lambda functions whose handler paths are referenced as dotted module strings from CDK infrastructure code, and (2) Sport_be currently uses `src/` as its import root configured in `pyproject.toml`, `mypy`, `ruff`, `pytest`, and `hatch` packaging.

## Glossary

- **Migration_System**: The overall process and its resulting artifacts (moved files, updated imports, updated configuration) that reorganize the Sport_be source tree into the target layout.
- **Source_Root**: The top-level code directory. Currently `src/`; the target Source_Root is `python/` to match the reference project.
- **Layered_Structure**: The current organization of `src/` into `domain`, `application`, `infrastructure`, and `interfaces` layers.
- **Feature_Module**: A self-contained directory under `python/api/` holding all code for one business area (e.g. `python/api/auth/`), following the reference convention.
- **Feature**: A business area of the application. The identified features are: `auth`, `registration`, `member`, `accountType`, `socialLogin`, plus supporting model areas `tenant` and `user`.
- **Common_Module**: The shared directory `python/api/common/` holding cross-feature code (configuration, persistence clients, shared DTOs/value objects, error types, shared HTTP helpers) that is not specific to a single Feature.
- **Naming_Convention**: The file and directory naming style. The reference uses `camelCase` for module file names and directory names.
- **Import_Statement**: Any Python `import` or `from ... import ...` statement that references a module by path within the project.
- **Handler_Path**: A dotted module-and-function string (e.g. `interfaces.http.handlers.auth_handler.handler`) used by the CDK infrastructure (`infra/stacks/app_stack.py`) to identify a Lambda entry point relative to the Source_Root.
- **Module_Mapping**: The documented, one-to-one correspondence between each existing source file in the Layered_Structure and its destination path in the target Feature_Module or Common_Module layout.
- **Test_Suite**: The pytest-based tests under `tests/`, including `unit`, `integration`, and `property` test groups.
- **Configuration_Files**: Project files that reference source paths or import roots: `pyproject.toml` (pytest `pythonpath`, `hatch` packages, `mypy` `mypy_path`, `ruff` `src` and `known-first-party`), and the CDK stack file `infra/stacks/app_stack.py`.
- **Behavior_Preservation**: The property that observable runtime behavior, API contracts, Lambda entry-point signatures, and test outcomes are unchanged by the Migration_System.

## Requirements

### Requirement 1: Target Folder Layout

**User Story:** As a backend developer, I want the source tree reorganized into feature modules under a `python/` root, so that the project structure matches the reference project's convention and new features have an obvious home.

#### Acceptance Criteria

1. THE Migration_System SHALL place all migrated application code under a Source_Root directory named `python/`.
2. THE Migration_System SHALL create exactly one Feature_Module directory under `python/api/` per named Feature, where the set of named Features is limited to exactly the five modules `auth`, `registration`, `member`, `accountType`, and `socialLogin`.
3. THE Migration_System SHALL create a `python/api/common/` Common_Module directory for code that is referenced by two or more Feature_Modules and is not specific to a single Feature.
4. THE Migration_System SHALL create a `python/tests/` directory that mirrors the Feature_Module layout, with exactly one test subdirectory per Feature whose name matches the corresponding Feature_Module name.
5. WHERE a Feature_Module contains code, THE Migration_System SHALL keep that module self-contained such that all code for one Feature resides within that Feature's directory, except for code explicitly assigned to the Common_Module.
6. THE Migration_System SHALL include an `__init__.py` file in every created Python package directory under `python/`.
7. THE Migration_System SHALL produce a target-layout document that lists every directory in the resulting `python/` tree, validated against the actual `python/` directory tree such that the document and the tree contain the same set of directories.
8. IF creating a target directory would conflict with an existing path, THEN THE Migration_System SHALL halt directory creation and produce an error indication identifying the conflicting path, without performing partial directory creation.

### Requirement 2: File and Module Mapping

**User Story:** As a backend developer, I want an explicit mapping from each current layered file to its new feature-module location, so that the migration is auditable and no file is lost or misplaced.

#### Acceptance Criteria

1. THE Migration_System SHALL produce a Module_Mapping that lists, for every Python source file currently under `src/`, the corresponding destination path under `python/`, such that the count of source-file entries in the Module_Mapping equals the total count of `.py` files under `src/`.
2. THE Migration_System SHALL assign each source file to exactly one destination path in the Module_Mapping, with no source path appearing more than once and no two source files mapped to the same destination path.
3. THE Migration_System SHALL map each source file whose responsibility belongs to a single Feature (controllers, handlers, use cases, DTOs, entities, value objects, repositories, mappers for the Features `auth`, `registration`, `member`, `accountType`, and `socialLogin`) into that Feature's Feature_Module under `python/api/<feature>`.
4. THE Migration_System SHALL map each cross-cutting file that is referenced by two or more Features (configuration, DynamoDB client setup, shared pagination DTOs, shared error types, shared HTTP response and error helpers, JWKS provider, shared port types) into the Common_Module.
5. WHERE a source file is referenced by two or more Features, THE Migration_System SHALL assign that file to a single Common_Module destination path and SHALL NOT assign it to any Feature_Module destination path.
6. THE Migration_System SHALL assign every source file under the `tenant` and `user` domain code to exactly one destination path that is either a Feature_Module or the Common_Module, with each such assignment recorded as an explicit entry in the Module_Mapping.
7. WHEN the Migration_System moves a file, THE Migration_System SHALL preserve the file's contents byte-for-byte except for lines that constitute Import_Statements and identifiers that must change to conform to the Naming_Convention.
8. IF a source file under `src/` has no corresponding destination entry in the Module_Mapping, THEN THE Migration_System SHALL reject the Module_Mapping and produce an error indication identifying each unmapped source file, without moving any file.
9. IF two or more source files are assigned to the same destination path in the Module_Mapping, THEN THE Migration_System SHALL reject the Module_Mapping and produce an error indication identifying the conflicting source files and destination path, without moving any file.

### Requirement 3: Naming Convention Conversion

**User Story:** As a backend developer, I want file and directory names converted from snake_case to the reference camelCase convention, so that the codebase is stylistically consistent with the reference project.

#### Acceptance Criteria

1. THE Migration_System SHALL name each Feature_Module directory using the camelCase form of its Feature name, where camelCase conversion removes each underscore and capitalizes the first letter of each word following an underscore while leaving the first word lowercase (for example `account_type` becomes `accountType` and `social_login` becomes `socialLogin`).
2. WHEN converting a migrated Python module file name from snake_case to camelCase, THE Migration_System SHALL apply the same underscore-removal and word-capitalization rule to the file name stem while preserving the `.py` extension.
3. WHERE the reference project defines a role suffix for a file's role (`<feature>Controller.py`, `<feature>Service.py`, `<feature>VM.py`) AND the migrated file maps to that role, THE Migration_System SHALL name the migrated file using the camelCase Feature name followed by the matching role suffix and the `.py` extension.
4. IF a migrated file has no role in the reference project's defined role-suffix set, THEN THE Migration_System SHALL apply only the camelCase stem conversion from criterion 2 without adding a role suffix and SHALL record the file as having no role mapping in the Module_Mapping.
5. THE Migration_System SHALL record in the Module_Mapping, for every file whose name changes under the Naming_Convention, both the original source file name and the renamed target file name.
6. IF two or more source files convert to the same target file name within the same Feature_Module directory, THEN THE Migration_System SHALL halt the conversion for that Feature_Module, leave the affected source files unchanged, and produce an error indication identifying the conflicting source file names.
7. WHERE a Python identifier (class, function, or variable name) is defined inside a migrated file, THE Migration_System SHALL leave that identifier byte-for-byte unchanged unless a separate requirement mandates its change.
8. THE Migration_System SHALL keep every `__init__.py` file named exactly `__init__.py` without applying camelCase conversion.

### Requirement 4: Import Path Updates

**User Story:** As a backend developer, I want every import statement updated to the new module paths, so that the application resolves all modules and runs without import errors after the migration.

#### Acceptance Criteria

1. WHEN the Migration_System relocates or renames a module, THE Migration_System SHALL update every Import_Statement in the project that references that module to the module's new path and name, covering absolute imports, relative imports, and `from ... import ...` forms.
2. THE Migration_System SHALL update project-internal Import_Statements in both the migrated source files and the Test_Suite files, and SHALL leave external third-party and standard-library Import_Statements unchanged.
3. IF an Import_Statement references a project-internal module that no longer exists at its original path after migration, THEN THE Migration_System SHALL update that Import_Statement to the module's new location within 1 update pass.
4. IF an Import_Statement references a project-internal module that cannot be mapped to a unique new location, THEN THE Migration_System SHALL leave the Import_Statement unchanged and record a diagnostic entry identifying the file, line number, and unresolved module name, and SHALL treat the migration as incomplete.
5. THE Migration_System SHALL update the `known-first-party` import roots and any `src`-based import configuration so that static analysis resolves 100% of project-internal modules against the new `python/` layout with zero unresolved-import findings.
6. WHEN the migration is complete, THE Migration_System SHALL leave zero unresolved project-internal Import_Statements, verified by importing every migrated application module and Test_Suite module without raising `ModuleNotFoundError` or `ImportError`.

### Requirement 5: Deployment and Entry-Point Wiring

**User Story:** As a developer responsible for deployment, I want the CDK infrastructure updated to reference the new Handler_Paths and Source_Root, so that the Lambda functions continue to deploy and execute against the migrated code.

#### Acceptance Criteria

1. WHEN a Lambda handler module is relocated or renamed, THE Migration_System SHALL update the corresponding Handler_Path string in `infra/stacks/app_stack.py` such that the dotted Handler_Path resolves to an existing module attribute under the new Source_Root.
2. THE Migration_System SHALL update the CDK Lambda code-asset source directory reference to the new Source_Root `python/` such that zero `src/` references remain in `infra/stacks/app_stack.py`.
3. THE Migration_System SHALL keep the exported Lambda handler function name for every migrated handler module such that each Handler_Path resolves to a callable entry point.
4. THE Migration_System SHALL keep the count of Lambda functions and the route-to-handler assignments defined in the CDK stack equal before and after migration.
5. THE Migration_System SHALL keep the AWS Lambda handler signature parameter names and order exactly as `handler(event, context)` for every migrated handler module.
6. IF a Handler_Path cannot be resolved to a callable after migration, THEN THE Migration_System SHALL halt and produce an error indication identifying the unresolved Handler_Path, leaving the pre-migration Handler_Path references unchanged.

### Requirement 6: Test Reorganization

**User Story:** As a backend developer, I want tests reorganized to mirror the feature-module layout, so that each feature's tests live alongside a predictable path and the suite still runs.

#### Acceptance Criteria

1. THE Migration_System SHALL reorganize the Test_Suite so that tests for a Feature reside under a `python/tests/<feature>/` directory whose name matches the corresponding `python/api/<feature>` Feature_Module name.
2. THE Migration_System SHALL preserve every existing test file in the reorganized Test_Suite, such that the count of test files after reorganization equals the count before, each mapped to exactly one destination path, with no test file remaining at its original pre-migration location.
3. IF a test file cannot be mapped to a Feature test directory, THEN THE Migration_System SHALL halt the reorganization, restore test files to their original locations, and produce an error indication identifying the unmappable test file.
4. THE Migration_System SHALL preserve the separation of `unit`, `integration`, and `property` test groups such that each migrated test file remains in a subpath identifying the same one of the three groups it belonged to before migration.
5. THE Migration_System SHALL update the pytest `testpaths` setting to reference `python/tests` and the `pythonpath` setting to reference the `python/` source location, with neither referencing any pre-migration `src/` location.
6. WHEN the reorganized Test_Suite is executed, THE Migration_System SHALL cause pytest to discover and collect 100% of the migrated test files with zero collection errors.

### Requirement 7: Configuration Updates

**User Story:** As a backend developer, I want all project configuration that references source paths updated to the new layout, so that build, type-check, lint, and test tooling operate on the migrated tree.

#### Acceptance Criteria

1. WHEN the migration executes, THE Migration_System SHALL update the `hatch` wheel packages setting in `pyproject.toml` to the Source_Root `python` such that the setting does not reference `src`.
2. WHEN the migration executes, THE Migration_System SHALL update the `mypy` `mypy_path` setting in `pyproject.toml` to the Source_Root `python` such that the setting does not reference `src`.
3. WHEN the migration executes, THE Migration_System SHALL update the `ruff` `src` setting in `pyproject.toml` to the Source_Root `python` such that the setting does not reference `src`.
4. WHEN the migration executes, THE Migration_System SHALL update the `ruff` `known-first-party` list in `pyproject.toml` to the Feature_Module import roots under `python` such that no entry references `src`.
5. WHEN the migration executes, THE Migration_System SHALL update the pytest `pythonpath` and `testpaths` settings in `pyproject.toml` to the Source_Root `python` and test locations under `python/tests` such that neither setting references `src`.
6. IF a Configuration_File update leaves a stale `src` reference, THEN THE Migration_System SHALL produce an error indication identifying the file and setting, without performing a partial update.

### Requirement 8: Behavior Preservation and Verification

**User Story:** As a backend developer, I want the migration to preserve all runtime behavior and be verified by the existing test suite, so that I can trust the refactoring introduced no regressions.

#### Acceptance Criteria

1. THE Migration_System SHALL preserve the observable runtime behavior of the application, limiting all changes to file locations, file names, Import_Statements, and configuration path references, such that no changes are made to function signatures, control flow, data transformations, or return values.
2. THE Migration_System SHALL leave the business logic within each migrated file byte-for-byte unchanged except for Import_Statements, such that a line-by-line comparison of each migrated file against its pre-migration version shows differences only in import lines.
3. WHEN the reorganized Test_Suite is executed after migration, THE Migration_System SHALL cause every test that passed before the migration to pass after the migration, with the count of passing tests being greater than or equal to the pre-migration passing count and zero newly failing tests attributable to the migration.
4. WHEN static type checking is run after migration, THE Migration_System SHALL produce zero new unresolved-import type errors relative to the pre-migration baseline, where the pre-migration count of such errors is recorded before migration begins.
5. IF the Test_Suite reports one or more failures caused by the migration, THEN THE Migration_System SHALL be corrected and the Test_Suite re-executed until the count of failures attributable to the migration reaches zero.
6. THE Migration_System SHALL preserve the public API contract of every Lambda handler, such that for identical request inputs the set of accepted HTTP methods, the route matching outcome, and the response shape (status code and body structure) are identical before and after migration.
7. WHEN the Test_Suite is executed after migration, THE Migration_System SHALL complete the full Test_Suite run and report a pass/fail result for every test within 600 seconds.
