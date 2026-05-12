# Orbit Staging Runbook

## Required Environment

- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `OPENAI_API_KEY`
- `CRON_SECRET`
- `RESEND_API_KEY`
- `REMINDER_FROM_EMAIL`
- `NEXT_PUBLIC_APP_URL`

## Validation Steps

1. Apply Supabase migrations in order against the staging project.
2. Run `npm run staging:check` with staging environment variables loaded.
3. Verify `public.search_interactions` exists and returns rows for an authenticated user.
4. Create two staging users and confirm RLS blocks cross-user reads for profiles, interactions, reminders, pending captures, events, enrichment jobs, and notification preferences.
5. Run the cron digest manually:

```bash
curl -X POST "$NEXT_PUBLIC_APP_URL/api/reminders/daily-digest" \
  -H "Authorization: Bearer $CRON_SECRET"
```

6. Confirm Resend delivers one grouped daily digest per user and `reminders.payload.providerMessageId` is stored.
7. Click an unsubscribe link and verify `notification_preferences.unsubscribed_at` is populated.
8. Run `npm test`, `npm run lint`, `npm run build`, and `STAGING_AUTH_STATE=./storage-state.json npm run test:e2e`.

## Rollback

- Disable the production cron schedule first.
- Remove or rotate `RESEND_API_KEY` if email delivery is misbehaving.
- Keep `notification_preferences.daily_digest_enabled=false` for affected users until the issue is corrected.
