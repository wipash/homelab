# Identity and user onboarding

Authelia **4.39.28** provides public authentication at **https://auth.mcgrath.nz**. LLDAP remains on the internal gateway at **https://lldap.mcgrath.nz**; neither its admin UI nor its LDAP port needs public exposure for onboarding.

To onboard a user:

1. From the internal network or tailnet, create their account in LLDAP with a deliverable email address and the appropriate application groups.
2. Send them their username and **https://auth.mcgrath.nz**. They select **Reset password?**, enter their username, and follow the emailed link to set their initial password.
3. They sign in and enroll their second factor. OIDC applications retain the `two_factor` authorization policy.

This is account creation plus email-verified password setup, not an invitation or self-registration system. Authelia sends recovery mail through the existing SMTP relay and updates LLDAP over the internal LDAP service.

The 4.39 upgrade uses the template configuration filter and JWKS schema while retaining the existing signing key and OIDC client credentials from 1Password. The `application_claims` policy preserves the identity claims previously included in ID tokens. Existing plaintext OIDC client secrets are still accepted by 4.39 but emit deprecation warnings; client-secret hashing is a separate migration.

Before deploying the upgrade, take a recoverable backup of the Authelia PostgreSQL database. Authelia performs schema migrations at startup; rolling back the image alone may not be sufficient after a database migration. Changes deploy through the normal Flux GitOps workflow.
