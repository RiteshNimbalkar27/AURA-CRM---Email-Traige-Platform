# API Limits and Deprecations Policy

**Version:** 1.0.0
**Last Updated:** 2024-01-01

This policy outlines the standard API rate limits, HTTP headers, versioning, and deprecation protocols for Nexus Software Inc. APIs.

## API Rate Limits
Rate limits are applied per plan tier:
- **Starter Plan**: 100 requests/minute, 5,000 requests/day
- **Professional Plan**: 500 requests/minute, 50,000 requests/day
- **Enterprise Plan**: Custom limits. Contact enterprise@nexus.example to request limit increases.

## Burst Limits & Throttling
We allow a burst limit of **2x the normal rate** for a duration of 60 seconds. Traffic exceeding the burst limit will be throttled.
When throttled, the API responds with an `HTTP 429 Too Many Requests` status and a `Retry-After` header indicating when requests can resume.

## Rate Limit Headers
All API responses include the following headers for client-side monitoring:
- `X-RateLimit-Limit`: The total number of requests permitted in the current window.
- `X-RateLimit-Remaining`: The number of requests remaining in the current window.
- `X-RateLimit-Reset`: The timestamp when the rate limit window will reset.

## Known Hard Limits
- Maximum file upload size: 100MB
- Maximum webhook payload size: 5MB

## Webhook Retry Policy
Failing webhooks use an exponential backoff retry strategy. The system attempts **3 retries over 24 hours** before the payload is dead-lettered and abandoned.

## API Versioning
Currently supported API versions are `/api/v2/` and `/api/v3/`.

### Deprecation Notice (v2 API)
- The v2 API is formally deprecated as of **2025-01-01**.
- The hard sunset date for v2 is **2026-06-30**.
- A full migration guide is available at docs.nexus.example/v3-migration.
- *Note: There are no reductions in current rate limits for v2 as of the publishing of this document.*

## Deprecation & Breaking Change Policy
- **Rate Limit Reductions**: Require a minimum of 6 months advance notice to all affected users.
- **Breaking Changes**: Require a minimum 12-month notice. This includes a major version bump, provision of a migration guide, and a mandated overlapping support window for both versions.

## SDK Support
Nexus maintains official SDKs in Python, JavaScript, Ruby, and Go. SDK support is guaranteed for the current major version and one previous major version.
