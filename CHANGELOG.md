# Changelog

## v0.2.11 - 2026-09-25

- Run CI explicitly on `v*` release tags so release validation exercises the same tests, package build, standalone `.pyz` smoke, and checksum artifact contract as main-branch pushes.
- Add the changelog project metadata URL and repository-contract coverage for release-tag CI and changelog metadata.

## v0.2.10 - 2026-09-24

- Add release-history documentation and repository-contract coverage so future releases keep changelog, README, CI, CodeQL, and downloadable artifact expectations in sync.

## v0.2.9 - 2026-09-24

- Modernized packaging license metadata to the current SPDX string format.
- Declared `license-files`, removed the deprecated MIT license classifier, raised the setuptools floor to `>=77`, and added regression tests for the metadata contract.

## v0.2.8 - 2026-09-20

- Fixed a crash when `smartctl` JSON reported `ata_smart_attributes.table` as explicit `null` instead of omitting the optional key.
- Added regression coverage for the null table shape and verified the release artifacts against `SHA256SUMS.txt`.

## v0.2.7 - 2026-09-19

- Fixed crashes when optional smartctl JSON objects such as `ata_smart_attributes` or `smartctl` were present with a `null` value.
- Preserved the intended fallback behavior: treat the candidate as having no usable SMART data and continue probing other `-d` types.
