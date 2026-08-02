# Ownership decision

The `alangan17/dbt-whydiff` work is migrated into this monorepo under
`integrations/dbt_whydiff` for the 0.1.x line. This keeps parity fixtures,
documentation, and compatibility changes reviewed with the Python engine.
The former repository should remain read-only with a pointer here; it is not a
second release source. A future split requires an ADR and automated parity tests
against a pinned `whydiff-core` version.
