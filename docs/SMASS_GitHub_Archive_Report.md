# SMASS GitHub Archive Report (G0)

Status: **`GITHUB_ARCHIVE = VERIFIED`**
(one platform limitation recorded in §8 — ref protection unavailable on the free
private-repo plan; archive integrity is instead pinned by immutable SHA evidence)

Generated: 2026-10-30 · Repository: `E:\PythonWeb\smass` · Author of run: DSH agent

> **No secret value appears in this document.** The compromised legacy secret is
> referred to only as *the legacy MD5/SECRET_KEY literal*, and every scanner hit is
> masked as `XXXX****(len=N)`.

---

## 1. Remote repository

| Field | Value |
| --- | --- |
| URL | https://github.com/MoRanzhi1203/smass-smart-campus |
| Owner | `MoRanzhi1203` (personal account, GitHub user id `127939275`) |
| Repository id | `1438846357` |
| Visibility | **private** (`private: true`, `visibility: "private"`) |
| Fork | false |
| Default branch | `archive/r10-baseline-82013b6` |
| Created | `2026-10-29T19:05:24Z` |
| First push | `2026-10-29T19:06:35Z` |
| Authenticated permissions | admin / maintain / push / triage / pull |

Name `smass-smart-campus` did not previously exist; existence was checked with
`GET /repos/MoRanzhi1203/smass-smart-campus` → `404` before creation. Nothing was
overwritten, force-pushed or repurposed.

Authentication used the **already-present** Git Credential Manager token for
`github.com` (a personal OAuth token belonging to the current machine user). No token
was requested from the user, printed, logged, or written to any file; the credential was
read in-process via `git credential fill`.

## 2. Pushed refs

| Ref | Remote SHA | Type |
| --- | --- | --- |
| `refs/heads/archive/r10-baseline-82013b6` | `a6b232810ac51f90b70a9e55bf2ab50d7c05f069` | sanitized archive branch |
| `refs/tags/archive-r10-baseline-20261030` | `6817a138543b95270f6337f8f567e274462dff93` | annotated tag object |
| `refs/tags/archive-r10-baseline-20261030^{}` | `a6b232810ac51f90b70a9e55bf2ab50d7c05f069` | dereferenced commit |

Only these two refs were pushed. `--force`, `--mirror`, `--all`, `--tags` and bulk
multi-branch push were **not** used. The other 8 local branches were deliberately not
pushed.

## 3. SHA mapping — original vs archived

| | SHA |
| --- | --- |
| Local original baseline (`feat/smass-r4-r10-integrated-platform`) | `82013b63a9109667621128dc4e4ae93a2dbb3f21` |
| Local raw HEAD (identical) | `82013b63a9109667621128dc4e4ae93a2dbb3f21` |
| Local sanitized equivalent of the same branch | `a6b232810ac51f90b70a9e55bf2ab50d7c05f069` |
| **Remote archive branch** | `a6b232810ac51f90b70a9e55bf2ab50d7c05f069` |
| **Remote archive tag → commit** | `6817a138543b95270f6337f8f567e274462dff93` → `a6b2328…` |

Machine-readable full object map (5,532 pairs): archive `reports\sha_mapping.json`
and `reports\SHA_MAPPING.md`.

Because the rewrite removed material from blobs, the sanitized SHA necessarily differs
from the original. The mapping is exact and reproducible, not a guess: it was captured
from `git fast-export --show-original-ids` paired with `git fast-import --export-marks`.

## 4. Why the raw history could not be pushed

The repository history contained a **previously committed legacy MD5 / Django SECRET_KEY
literal** — the same value the directive identifies as compromised. It was never a
current-tree-only issue, so `HEAD`-only scanning would have been worthless.

Full reachable-history scan (tool: `scan_history.py`, method:
`git cat-file --batch-all-objects` over every object + every commit message + every
annotated tag body):

```
objects          = {blob: 5446, commit: 87, tree: 656, tag: 1}
text blobs read  = 5390   (56 binary skipped by extension/NUL marker)
bytes scanned    = 37,588,434
commits scanned  = 87
refs scanned     = 10
findings         = 89  (by rule: SEC-MD5-HEX32 28, PII-CN-MOBILE 28,
                        PII-CN-IDCARD 22, SEC-DJANGO-INSECURE 5, PII-EMAIL 4,
                        SEC-DB-CREDENTIAL 1, SEC-HARDCODED-SECRET 1)
```

### Blobs containing the compromised literal — 5 blobs / 4 paths

| path | nature |
| --- | --- |
| `app01/services/accounts.py` | `LEGACY_MD5_SECRET_KEY` literal (two blob generations) |
| `docs/SMASS_PMR_Executive_Report.md` | same literal quoted inside a report |
| `scripts/pmr_synthetic_fixture.py` | same literal used for fixture generation |
| `smass/settings.py` | historical hardcoded `SECRET_KEY` (removed from HEAD at `06d210e`) |

### Findings adjudicated as non-compromising

| finding | adjudication |
| --- | --- |
| `PII-CN-IDCARD` ×22 | **synthetic** fixtures, e.g. `500000199001010011` (province `500000`, birth `1990-01-01`, seq `001`) |
| `PII-CN-MOBILE` ×28 | **synthetic** fixtures, e.g. `13800000000`, `13900000000` |
| `PII-EMAIL` ×4 | project documentation addresses + noreply git identity |
| `SEC-DB-CREDENTIAL` ×1 | **false positive**: `.env.example` `DB_PASSWORD=change-me` placeholder |
| `SEC-MD5-HEX32` ×28 | 32-hex artifact/lock fingerprints in `docs/dsh_run/*.json`, not password dumps |
| `SEC-HARDCODED-SECRET` ×1 | the `smass/settings.py` historical SECRET_KEY (same literal as above) |

Negative finding that matters: the **real `.env` (live DB password) has never entered
Git history** — `git rev-list --all --objects | grep '\.env$|\.env\.'` returns nothing,
and `.gitignore` covers `.env`, `.env.*`, `*.pem`, `*.key`, `secrets/`, `*.sql`,
`backups/`.

## 5. Sanitization technique

Tool: `sanitize_history.py`. The user's working repository was **only read**.

```
git fast-export --all --signed-tags=strip --tag-of-filtered-object=rewrite \
                --show-original-ids --reencode=no --use-done-feature
      │
      ├─ streaming parse of the fast-import stream
      ├─ byte-level redaction of every `data <n>` payload
      │     (blob contents AND commit/tag messages)
      └─ git fast-import  →  separate repository at <archive>\sanitized_repo
```

Redaction rules, applied in order:

1. exact replacement of the compromised legacy secret literal
   → `REDACTED__LEGACY_SECRET_KEY__INJECT_FROM_LOCAL_RESTRICTED_STORE`
2. generic neutralisation of any remaining `django-insecure-<20+ chars>` literal
   → `django-insecure-REDACTED__SEE_LOCAL_RESTRICTED_ARCHIVE
3. **preserve verbatim** the documented, non-secret dev defaults
   `django-insecure-REDACTED__SEE_LOCAL_RESTRICTED_ARCHIVE and
   `dev-insecure-secret-key-for-smass-only`

Rule 3 was added after a first pass over-redacted the documented dev default and broke
reproducibility of the archived tree. It was caught by re-grepping the archived tree
(`git grep -F django-insecure-dev-only-…` returned nothing) and fixed **before** the
final archive was cut. The archived dev default now resolves.

Result:

```
blobs_touched         = 8
blob_replacements     = 8
message_replacements  = 0     (no secret ever appeared in a commit message or tag body)
refs rebuilt          = 10
object map entries    = 5532
author/committer/date/topology preserved
```

## 6. Verification evidence

### 6.1 Independent leak cross-check (not the scanner's own word)

Tool: `verify_sanitized.py`. It loads the secret from the **original** worktree (so the
check cannot become vacuous), then searches every physical object in the target repo —
reachable *and* unreachable — plus all commit/tag messages, plus `git grep -F` across all
refs.

Run against the **locally built sanitized repo**:

```
source_secrets_checked = 1
object_counts          = {blob: 5446, tree: 656, commit: 87, tag: 1}
blobs_scanned          = 5446
total_objects          = 6190
blob_leaks = []   message_leaks = []   git_grep_leaks = []
VERDICT = CLEAN          exit 0
```

Run against the **remote clone** (fresh `git clone` of the pushed branch — i.e. what
GitHub actually stores and serves):

```
blobs_scanned = 5446   total_objects = 6190
blob_leaks = []   message_leaks = []   git_grep_leaks = []
VERDICT = CLEAN          exit 0
```

### 6.2 Remote identity — the archive is exactly what was verified

```
local sanitized sha : a6b232810ac51f90b70a9e55bf2ab50d7c05f069
remote clone HEAD  : a6b232810ac51f90b70a9e55bf2ab50d7c05f069   identical
root tree local    : 7e23d441bb872116a102292cd329164ab18b9cbf
root tree remote   : 7e23d441bb872116a102292cd329164ab18b9cbf   identical
files local/remote : 5140 / 5140     file maps identical: true
blob diff count    : 0
```

### 6.3 Structural fidelity — blast radius is exactly 3 files

Same-branch `git ls-tree -r` comparison, original vs sanitized:

```
raw  82013b6 : 5140 files
san  a6b2328 : 5140 files
files only in raw        = 0
files only in sanitized  = 0
file modes changed       = 0
blobs byte-identical     = 5137
blobs changed            = 3
    app01/services/accounts.py
    docs/SMASS_PMR_Executive_Report.md
    scripts/pmr_synthetic_fixture.py
```

`smass/settings.py` is **unchanged** after rule 3, because at HEAD it only carries the
allow-listed dev default.

### 6.4 Restorability

```
git worktree add --detach <archive>\restore_test feat/smass-r4-r10-integrated-platform
  → 5140 files checked out; manage.py present; smass/settings.py present
python -m compileall -q smass app01 smass_organization smass_operations
  → exit code 0   (archived tree is syntactically valid Python)
```

The remote clone itself (`remote_verify/`, 5140 tracked files, 87 commits) is a second,
independent restorability proof from GitHub's own bytes.

## 7. Offline baseline and restoration

| Artifact | Path | Integrity |
| --- | --- | --- |
| Full offline worktree snapshot (tracked + untracked + `.git`) | `<archive>\raw_snapshot\` | 11,691 files; `manifest_source.csv` vs `manifest_snapshot.csv`: 0 missing, 0 extra, 1 unreadable-at-capture (`logs/smass.log`, held open by a live process) |
| Complete Git bundle (9 branches + 1 tag + HEAD) | `<archive>\SMASS_BASELINE_82013b6_20261030_024054.bundle` (8.79 MB) | SHA256 `58D5C8A8AFF4FCAE632F9EE3AC683CCAF0A65D52757EFA332EC061E7031277B4`; `git bundle verify` → *"records a complete history"* |
| Sanitized clone | `<archive>\sanitized_repo\` | 6,190 objects, CLEAN |
| Remote verification clone | `<archive>\remote_verify\` | 5,140 files, CLEAN |
| Scan evidence | `<archive>\history_scan\`, `<archive>\history_scan_sanitized\` | JSON + Markdown |

Restore the **original unmodified** history (contains the compromised secret — local
restricted use only):

```powershell
cd E:\PythonWeb
git clone SMASS_BASELINE_82013b6_20261030_024054.bundle smass_restored
cd smass_restored
git branch -a          # 9 branches + tag restored
git checkout feat/smass-r4-r10-integrated-platform   # -> 82013b6
```

Restore the **sanitized** archive from GitHub:

```powershell
git clone --branch archive/r10-baseline-82013b6 https://github.com/MoRanzhi1203/smass-smart-campus.git smass_archive_restored
cd smass_archive_restored
git rev-parse HEAD    # must equal a6b232810ac51f90b70a9e55bf2ab50d7c05f069
```

**The bundle must never be uploaded to GitHub or included in any downloadable
deliverable** — it intentionally contains the compromised history.

## 8. Platform limitation (recorded honestly)

| protection | outcome |
| --- | --- |
| Branch protection on `archive/r10-baseline-82013b6` | **403** — *"Upgrade to GitHub Pro or make this repository public to enable this feature."* |
| Tag protection rule for `archive-r10-baseline-20261030` | **404 Not Found** (feature unavailable on this plan) |

`TAG_PROTECTION = NOT_AVAILABLE_ON_PLAN`. Upgrading to a paid plan would
violate the "no paid cloud resources" constraint, and making the repository public would
violate the "private archive" requirement. Archive integrity is therefore pinned instead
by immutable evidence: the annotated tag object SHA (`6817a13…`), the commit SHA
(`a6b2328…`), the root tree SHA (`7e23d44…`), and the fact that any rewrite of either ref
would change those SHAs and be detectable by re-running §6.1/§6.2.

## 9. Safety invariants held

- `E:\PythonWeb\smass` working tree: **0 files modified**, 0 commits created during G0
- no `reset` / `clean` / `checkout` / `rebase` / in-place history rewrite
- no database contacted; official `smass` DB untouched and read-only; `AUTH_USER_MODEL` untouched
- no secret, token or password written to any Markdown, JSON, log or command line
- archive directory lives outside the repository and is excluded from every push
- no public visibility, no Pages, no Actions secrets, no deployment, no paid resource

## 10. Verdict

`GITHUB_ARCHIVE = VERIFIED`

- private remote exists and is owned by the authenticated personal account
- only sanitized objects were pushed (branch + annotated tag), verified by an
  independent clone-side secret scan returning `CLEAN` over 6,190 objects
- the sanitized archive is byte-identical to the locally verified artifact
- the original unmodified history is preserved only in a local restricted bundle
- a documented `original ↔ sanitized` SHA mapping exists for rollback/restoration

Gate for source modification is therefore **OPEN**. Development continues on an isolated
branch created from the validated local HEAD; the compromised raw history is never pushed.
