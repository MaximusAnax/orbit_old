# Orbit Production Launch

Target URL: `https://orbit-six-blond.vercel.app`

## Vercel

- Create a new Vercel project from this repository.
- Framework preset: Next.js.
- Install command: `npm install`.
- Build command: `npm run build`.
- Use the Vercel production alias: `orbit-six-blond.vercel.app`.
- Set production environment variables:
  - `NEXT_PUBLIC_APP_URL=https://orbit-six-blond.vercel.app`
  - `NEXT_PUBLIC_SUPABASE_URL`
  - `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`
  - `SUPABASE_SERVICE_ROLE_KEY`
  - `OPENAI_API_KEY`

Reminder email variables are intentionally omitted for first launch.

## Domain

No custom domain is required for this launch. Keep using the Vercel production alias until a later custom-domain pass.

## Supabase

- Create or select the production Supabase project.
- Apply every migration in `supabase/migrations`.
- Configure Auth site URL: `https://orbit-six-blond.vercel.app`.
- Add redirect URL: `https://orbit-six-blond.vercel.app/auth/callback`.
- Confirm Google provider is enabled with the production OAuth client.

## Google OAuth

- Authorized JavaScript origin: `https://orbit-six-blond.vercel.app`.
- Authorized redirect URI: the Google callback URL shown by the production Supabase project.

## Validation

Run locally before deploying:

```bash
npm run lint
npm run test
npm run build
NEXT_PUBLIC_APP_URL=https://orbit-six-blond.vercel.app npm run production:check
```

After deployment and DNS verification:

- Open `https://orbit-six-blond.vercel.app`.
- Confirm landing capture renders.
- Start a capture before auth.
- Sign in with Google.
- Confirm the memory commits to a profile.
- Confirm `/app`, search, profile edit, and follow-up actions work.
