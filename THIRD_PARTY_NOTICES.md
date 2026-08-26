# Third-party notices

Destiny's own source is MIT licensed. Direct runtime dependencies are not
vendored and retain their own licenses:

| Component | Pinned version | Role | License |
|---|---:|---|---|
| lunar-python | 1.4.8 | Chinese calendar and Bazi calculations | MIT |
| tzdata | 2026.3 | Pinned IANA timezone database | Apache-2.0 |
| iztro | 2.5.8 | Zi Wei Dou Shu chart engine | MIT |
| httpx | 0.28.1 | Optional LLM HTTP client | BSD-3-Clause |
| Skyfield | 1.55 | Optional JPL SPK astronomy interface | MIT |
| NumPy | 2.2.6 (`<3.11`), 2.4.6 (`3.11`), 2.5.2 (`>=3.12`) | Optional incremental-research ridge linear algebra | BSD-3-Clause project; bundled components vary |

Their transitive dependencies remain governed by their own notices. Notably,
the installed Python environment can include Certifi under MPL-2.0. NumPy wheels
can bundle additional compatibly licensed numerical runtimes; inspect the
installed distributions for their complete notices and license texts.

JPL DE440/DE440s/DE441 kernels are external data files and are not included in
this repository. Users obtain them from JPL/NAIF, retain the source URL and file
hash, and comply with applicable source terms. Destiny is not endorsed by NASA or JPL.

Swiss Ephemeris and `pyswisseph` are intentionally not dependencies. Swiss
Ephemeris uses an AGPL/commercial dual-license model that requires a separate
licensing decision before integration or distribution.
