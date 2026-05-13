# Orbit Production Launch

Target URL: `https://orbit.abdoulndiongue.com`

## Vercel

- Create a new Vercel project from this repository.
- Framework preset: Next.js.
- Install command: `npm install`.
- Build command: `npm run build`.
- Add production domain: `orbit.abdoulndiongue.com`.
- Set production environment variables:
  - `NEXT_PUBLIC_APP_URL=https://orbit.abdoulndiongue.com`
  - `NEXT_PUBLIC_SUPABASE_URL`
  - `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`
  - `SUPABASE_SERVICE_ROLE_KEY`
  - `OPENAI_API_KEY`

Reminder email variables are intentionally omitted for first launch.

## DNS

Add this DNS record in Cloudflare where `abdoulndiongue.com` is managed:

- Type: `A`
- Name: `orbit`
- IPv4 address: `76.76.21.21`

Wait for Vercel domain verification and TLS provisioning before final smoke testing.

## Supabase

- Create or select the production Supabase project.
- Apply every migration in `supabase/migrations`.
- Configure Auth site URL: `https://orbit.abdoulndiongue.com`.
- Add redirect URL: `https://orbit.abdoulndiongue.com/auth/callback`.
- Confirm Google provider is enabled with the production OAuth client.

## Google OAuth

- Authorized JavaScript origin: `https://orbit.abdoulndiongue.com`.
- Authorized redirect URI: the Google callback URL shown by the production Supabase project.

## Validation

Run locally before deploying:

```bash
npm run lint
npm run test
npm run build
NEXT_PUBLIC_APP_URL=https://orbit.abdoulndiongue.com npm run production:check
```

After deployment and DNS verification:

- Open `https://orbit.abdoulndiongue.com`.
- Confirm landing capture renders.
- Start a capture before auth.
- Sign in with Google.
- Confirm the memory commits to a profile.
- Confirm `/app`, search, profile edit, and follow-up actions work.
