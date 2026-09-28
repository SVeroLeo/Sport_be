# Implementation Plan: Folder Structure Migration

## Overview

This plan migrates the Sport_be backend from a layered tree under `src/` to a feature-module tree under `python/`, following the Module_Mapping, config plan, test-reorganization plan, and 14 correctness properties in the design. The migration is a pure refactoring: only file locations, file names, import statements, and config path references change.

The work is ordered so the codebase stays coherent and verifiable at each boundary:

1. Capture pre-migration baselines **before** anything moves (test counts, mypy unresolved-import count, CDK function/route counts).
2. Build the migration tooling (name converter, inventory scanner, fan-out analyzer, mapping builder + validation) as pure, testable functions.
3. Create the target `python/` package skeleton with `__init__.py` in every package.
4. Move + rename files and rewrite imports, migrating Common (tenant/user/shared) first since features depend on it, then each feature. This keeps the project import-coherent at task boundaries.
5. Reorganize tests to mirror the feature layout.
6. Update configuration (pyproject.toml, CDK app_stack.py, lambda_bundling.py) last.
7. Verify: import sweep, mypy vs baseline, CDK/handler resolution, full pytest vs baseline, and zero stale `src` references.

Implementation language: **Python** (the design specifies Hypothesis, pytest, mypy, and Python CDK — no pseudocode).

## Tasks

- [x] 1. Capture pre-migration baselines
  - [x] 1.1 Write a baseline-capture script that records test and type-check baselines
    - Run `pytest` collection + run and record the total test count and the passing test count to a baseline artifact (e.g. `.migration/baseline.json`)
    - Run `mypy` and record the count of unresolved-import errors (the Req 8.4 baseline)
    - Parse `infra/stacks/app_stack.py` and record the Lambda-function count and the route→handler assignments (the Req 5.4 / 8.6 baseline)
    - Record the total count of `.py` files under `src/` (the Req 2.1 inventory-count baseline)
    - _Requirements: 8.3, 8.4, 5.4, 8.6, 2.1_

- [x] 2. Build the migration tooling core (pure functions)
  - [x] 2.1 Implement the Name Converter
    - Implement `to_camel(stem)`: remove each underscore, capitalize the first letter of each following word, keep the first word lowercase, preserve `.py`
    - Implement `apply_role(camel_stem, role)` for roles `Controller`, `Service`, `VM`, `Handler`, and `None`
    - Never convert `__init__.py` (return it unchanged)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.8_

  - [x] 2.2 Write property test for camelCase conversion
    - **Property 1: camelCase conversion is deterministic and idempotent on already-camel stems**
    - **Validates: Requirements 3.1, 3.2**

  - [x] 2.3 Write property test for `__init__.py` preservation
    - **Property 2: `__init__.py` is never renamed**
    - **Validates: Requirements 3.8**

  - [x] 2.4 Write unit tests for concrete name conversions
    - `account_type` → `accountType`, `social_login` → `socialLogin`, `i_user_repository` → `iUserRepository`, `__init__.py` → `__init__.py`
    - _Requirements: 3.1, 3.2, 3.4, 3.8_

  - [x] 2.5 Implement the Inventory Scanner and Fan-out Analyzer
    - Implement `scan_sources(root) -> set[Path]` returning every `.py` under `src/`
    - Parse the internal import graph and implement `feature_fanout(module) -> set[Feature]`
    - _Requirements: 2.1, 2.4, 2.5_

- [x] 3. Build and validate the Module_Mapping
  - [x] 3.1 Implement the Mapping Builder
    - Produce a `MappingEntry` per source file (source_path, destination_path, original_name, target_name, role, target_feature) using the Name Converter and fan-out rule
    - Apply the fan-out decision rule: modules imported by ≥2 Features → `python/api/common/`; modules imported by exactly one Feature → that feature
    - Record original-name/new-name pairs and a "no role" flag where applicable
    - Encode the concrete Module_Mapping table from the design (auth, registration, member, accountType, socialLogin, common tenant/user/errors/config/http/ports)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.4, 3.5_

  - [x] 3.2 Implement Module_Mapping validation (transactional planning boundary)
    - Reject with an unmapped-file error listing each unmapped source when any `.py` under `src/` has no entry (move nothing)
    - Reject with a collision error identifying the conflicting sources + destination when two sources map to one destination (move nothing)
    - Halt per-feature conversion and report conflicting names when two source names convert to the same target within one feature
    - Assert `count(source entries) == count(.py under src/)` before any move
    - _Requirements: 2.8, 2.9, 3.6_

  - [x] 3.3 Write property test for mapping totality
    - **Property 3: Mapping is total over the source inventory**
    - **Validates: Requirements 2.1, 2.8**

  - [x] 3.4 Write property test for destination injectivity
    - **Property 4: Mapping is injective on destinations (no collisions)**
    - **Validates: Requirements 2.2, 2.9, 3.6, 1.8**

  - [x] 3.5 Write property test for source-path uniqueness
    - **Property 5: Source paths are unique (no source mapped twice)**
    - **Validates: Requirements 2.2**

  - [x] 3.6 Write property test for fan-out placement
    - **Property 6: Cross-feature files land in Common, single-feature files land in their feature**
    - **Validates: Requirements 2.3, 2.4, 2.5**

  - [x] 3.7 Write property test for tenant/user explicit mapping
    - **Property 7: tenant and user source files are explicitly mapped**
    - **Validates: Requirements 2.6**

- [x] 4. Checkpoint - Tooling and mapping validated
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Create the target `python/` package skeleton
  - [x] 5.1 Create the `python/` tree with package initializers
    - Create `python/api/`, the five feature dirs (`auth`, `registration`, `member`, `accountType`, `socialLogin`), and `python/api/common/` with its sub-packages (`tenant`, `user`, `valueObjects`, `errors`, `config`, `http`, `ports`, `dtos`, `auth`)
    - Create `python/tests/` mirroring the feature layout with one subdir per feature plus `common`
    - Add an `__init__.py` in every created Python package directory
    - Halt with a conflicting-path error if a target directory collides with an existing path (no partial creation)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6, 1.8_

- [x] 6. Implement the File Mover and Import Rewriter
  - [x] 6.1 Implement the File Mover (byte-for-byte moves via recorded manifest)
    - Move each file to its destination preserving contents byte-for-byte, recording an old→new manifest for rollback
    - Operate only after the Mapping Builder validates
    - _Requirements: 2.7, 8.1, 8.2_

  - [x] 6.2 Implement the Import Rewriter
    - Rewrite every project-internal `import` / `from ... import ...` (absolute and relative) in moved sources and test files to the new dotted path within one update pass
    - Leave stdlib/third-party imports unchanged
    - When an internal module cannot be mapped to a unique new location, leave the import unchanged and record a diagnostic (file, line, module) and mark the migration incomplete
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [x] 6.3 Write property test for content-diff-only
    - **Property 8: File contents change only on import lines**
    - **Validates: Requirements 2.7, 8.1, 8.2**

  - [x] 6.4 Write property test for import-rewrite target uniqueness/diagnosis
    - **Property 10: Import rewrite targets are unique or diagnosed**
    - **Validates: Requirements 4.4**

- [x] 7. Migrate Common_Module code (features depend on it, so move it first)
  - [x] 7.1 Move and rewrite tenant, user, and shared value-object code into `python/api/common/`
    - Move tenant/user entities, value objects, ports, repositories, and mappers to `common/tenant/`, `common/user/`, `common/valueObjects/` per the mapping table
    - Rewrite imports in the moved files
    - _Requirements: 2.4, 2.5, 2.6, 4.1, 4.3_

  - [x] 7.2 Move and rewrite shared errors, config, ports, and HTTP helpers into `python/api/common/`
    - Move domain errors → `common/errors/`, cognito/JWKS/DynamoDB/environment → `common/auth/` and `common/config/`, shared ports/DTOs → `common/ports/` and `common/dtos/`, response builder/error handler/middleware/api_response → `common/http/`, and the main `composition_root.py` → `common/compositionRoot.py`
    - Rewrite imports in the moved files
    - _Requirements: 2.4, 2.5, 4.1, 4.3_

- [x] 8. Migrate the `auth` feature
  - [x] 8.1 Move and rewrite auth controller, handler, use cases, DTOs, and entities into `python/api/auth/`
    - Apply role suffixes (`authController`, `authHandler`) and camelCase stems per the mapping table
    - Rewrite imports to reference `api.auth.*` and `api.common.*`
    - _Requirements: 2.3, 3.3, 4.1, 4.3_

- [x] 9. Migrate the `registration` feature
  - [x] 9.1 Move and rewrite registration controller, handlers, and use cases into `python/api/registration/`
    - Include `postConfirmationHandler` (registration-domain Cognito trigger)
    - Rewrite imports to reference `api.registration.*` and `api.common.*`
    - _Requirements: 2.3, 3.3, 4.1, 4.3_

- [x] 10. Migrate the `member` feature
  - [x] 10.1 Move and rewrite member controller, handler, use cases, DTOs, entities, value objects, port, repository, and mapper into `python/api/member/`
    - Rewrite imports to reference `api.member.*` and `api.common.*`
    - _Requirements: 2.3, 3.3, 4.1, 4.3_

- [x] 11. Migrate the `accountType` feature
  - [x] 11.1 Move and rewrite accountType controller, handler, use cases, DTOs, entity, value object, port, repository, and mapper into `python/api/accountType/`
    - Rewrite imports to reference `api.accountType.*` and `api.common.*`
    - _Requirements: 2.3, 3.1, 3.3, 4.1, 4.3_

- [x] 12. Migrate the `socialLogin` feature
  - [x] 12.1 Move and rewrite oauth controller, handler, composition root, use cases, DTOs, and state token into `python/api/socialLogin/`
    - Rewrite imports to reference `api.socialLogin.*` and `api.common.*`
    - _Requirements: 2.3, 3.1, 3.3, 4.1, 4.3_

- [x] 13. Checkpoint - All source migrated and import-coherent
  - Ensure all tests pass, ask the user if questions arise.

- [x] 14. Reorganize the Test_Suite
  - [x] 14.1 Implement and run test reorganization into `python/tests/<feature>/<group>/`
    - Map every test file to `python/tests/<feature>/{unit,integration,property}/` per the design's test data model, preserving the group segment and classifying legacy `tests/domain/**` and loose root files by subject
    - Preserve every test file (count after == count before), each to exactly one destination, none left at its original location; move `conftest.py` to `python/tests/conftest.py`
    - Rewrite project-internal imports in the moved test files
    - Halt, restore test files to original locations, and report the unmappable file if a test cannot be mapped to a feature test dir
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 4.2_

  - [x] 14.2 Write property test for test group preservation
    - **Property 12: Test group is preserved across reorganization**
    - **Validates: Requirements 6.4**

  - [x] 14.3 Write property test for test-file count and one-to-one placement
    - **Property 13: Test-file count and one-to-one placement are preserved**
    - **Validates: Requirements 6.2**

- [x] 15. Update configuration and deployment wiring
  - [x] 15.1 Update `pyproject.toml` to the `python/` layout
    - Update hatch wheel `packages`, `mypy.mypy_path`, `ruff.src`, `ruff.lint.isort.known-first-party` (→ `["api"]`), and pytest `pythonpath`/`testpaths` (→ `python` / `python/tests`)
    - Emit an error identifying the file + setting if any stale `src` reference remains (no partial update)
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 6.5_

  - [x] 15.2 Update CDK `infra/stacks/app_stack.py` handler paths and code-asset source
    - Rewrite the six Handler_Paths to `api.<feature>.<x>Handler.handler` per the Handler_Path mapping table
    - Repoint the Lambda code-asset source directory to `python/` so zero `src/` references remain
    - Keep the Lambda-function count and route→handler assignments unchanged
    - Halt and report the unresolved Handler_Path (leaving pre-migration references unchanged) if a path cannot resolve to a callable
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.6_

  - [x] 15.3 Update `infra/lambda_assets/lambda_bundling.py` to bundle `python/`
    - Repoint `_SRC_PATH`, the bundle `cp` command, and the CDK asset `exclude` globs from `src` / `src/**` to `python` / `python/**`
    - _Requirements: 5.2, 7.6_

  - [x] 15.4 Write property test for no stale `src` reference in configuration
    - **Property 14: No stale `src` reference remains in configuration**
    - **Validates: Requirements 5.2, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6**

  - [x] 15.5 Write unit tests for config scan and Handler_Path resolution
    - Assert each of the five `pyproject.toml` settings equals its post-migration value and contains no `src`; grep `app_stack.py` and `lambda_bundling.py` for zero `src` path matches
    - For each of the six handlers, import the new module and assert `handler` exists, is callable, and its first two params are `(event, context)`
    - _Requirements: 5.1, 5.3, 5.5, 7.6_

- [x] 16. Verification against baselines
  - [x] 16.1 Run the import-resolution sweep
    - Enumerate every `.py` under `python/` and every test module, import each, and assert no `ImportError` / `ModuleNotFoundError`
    - _Requirements: 4.5, 4.6, 6.6_

  - [x] 16.2 Write property test for post-migration import resolution
    - **Property 9: Every project-internal import resolves post-migration**
    - **Validates: Requirements 4.1, 4.3, 4.6, 6.6**

  - [x] 16.3 Write property test for Handler_Path callable resolution
    - **Property 11: Every Handler_Path resolves to a `handler(event, context)` callable**
    - **Validates: Requirements 5.1, 5.3, 5.5, 5.6**

  - [x] 16.4 Run mypy and pytest, compare to baselines, and drive the correction loop
    - Assert new unresolved-import mypy errors ≤ the recorded baseline
    - Run the full pytest suite; assert passing count ≥ baseline with zero new migration-attributable failures, completing within 600 seconds
    - Assert the CDK Lambda-function count and route→handler assignments are unchanged vs baseline
    - If migration-attributable failures exist, correct and re-run until they reach zero
    - _Requirements: 8.3, 8.4, 8.5, 8.6, 8.7, 5.4_

  - [x] 16.5 Validate the target-layout document against the actual `python/` tree
    - Produce the target-layout document listing every directory in `python/` and assert it contains the same set of directories as the actual tree
    - _Requirements: 1.5, 1.7_

- [x] 17. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test tasks and can be skipped for a faster MVP; core migration tasks are never optional.
- Each task references specific requirements for traceability.
- Common_Module code is migrated before the five features because every feature depends on it, keeping the tree import-coherent at task boundaries.
- File moves are staged behind mapping validation and executed via a recorded old→new manifest so any post-move failure can be rolled back by replaying the manifest in reverse.
- Property tests use Hypothesis (already a dev dependency), minimum 100 iterations, each tagged with its design property number.
- Verification is strictly automated (import sweep, mypy, pytest, config scan, CDK assertions) — no manual end-to-end runs or deployments are part of this plan.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1", "2.5"] },
    { "id": 1, "tasks": ["2.2", "2.3", "2.4", "3.1"] },
    { "id": 2, "tasks": ["3.2", "3.3", "3.4", "3.5", "3.6", "3.7"] },
    { "id": 3, "tasks": ["5.1"] },
    { "id": 4, "tasks": ["6.1", "6.2"] },
    { "id": 5, "tasks": ["6.3", "6.4", "7.1"] },
    { "id": 6, "tasks": ["7.2"] },
    { "id": 7, "tasks": ["8.1", "9.1", "10.1", "11.1", "12.1"] },
    { "id": 8, "tasks": ["14.1"] },
    { "id": 9, "tasks": ["14.2", "14.3", "15.1", "15.2", "15.3"] },
    { "id": 10, "tasks": ["15.4", "15.5", "16.1"] },
    { "id": 11, "tasks": ["16.2", "16.3", "16.4", "16.5"] }
  ]
}
```
