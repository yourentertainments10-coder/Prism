# Prism API Registry

The registry has two independent inputs:

1. `data/api_catalog.json` is discovered metadata imported offline from the
local `public-apis/README.md` checkout. Catalogue entries are marked
`discovered`, have unknown health, and are never executable by themselves.
2. `data/providers/*.json` contains reviewed GET configurations. The runtime
loads only these definitions, and each one must point to a name/category in
the discovered catalogue.

The importer does not clone repositories, contact the separate public-apis JSON
service, make API requests, or use an AI provider:

```powershell
env\Scripts\python.exe -m prism_superagent.api_registry.discovery `
  --source public-apis `
  --output prism_superagent/api_registry/data/api_catalog.json
```

The generated snapshot records the source commit, README hash, import time,
categories, entries, and parser issues. The current snapshot was imported from
commit `da95f28e9eeb9cb2e5498b0636d25570ca9831e5` and contains 1,966 entries in
51 categories. One malformed upstream row has a sixth cell; its first five
catalogue fields are imported and the extra cell is preserved and reported.

## Reviewed providers

The initial configurations are Open-Meteo geocoding, Frankfurter currency
rates, and Open Library book search. They are separate from catalogue data and
use fixed HTTPS host allowlists, GET only, declared parameters, bounded
responses, configured JSON checks, a short success-only cache, and response
hashes. Provider documentation was reviewed; no live API calls were made while
configuring or testing them. Pricing and data authority are not inferred from
catalogue metadata or a successful HTTP response.

Open Library requires `PRISM_API_CONTACT` so its configured User-Agent can
identify the client as requested by its usage guidance. Until set, the book
provider is unavailable and the existing Prism fallback is used.

Capability matching is deterministic and currently supports explicit book
search, currency rate/conversion, and geocoding requests. Provider health is
measured only when a user request calls a provider; Prism performs no startup
probes. Health and response cache state are process-local in this first version.
