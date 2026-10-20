# Publishing to GitHub

The repository is prepared for a public GitHub release. The proprietary
Android APK and local tool configuration are ignored by Git.

## 1. Check the tree

```bash
git status
git log --oneline
.venv/bin/python -m unittest discover -s tests -v
```

`git status` must not list `MR Star - v1.0.0.apk`, `opencode.json`, or `.venv/`.

## 2. Create and push the repository

With the GitHub CLI:

```bash
gh repo create MR-Star-desktop \
  --public \
  --source=. \
  --remote=origin \
  --push
```

Or with an existing empty repository:

```bash
git remote add origin git@github.com:<owner>/MR-Star-desktop.git
git push -u origin main
```

The `CI` workflow runs automatically on the first push and on pull requests.

## 3. Tag the initial release

```bash
git tag -a v1.0.0 -m "MR Star Desktop 1.0.0"
git push origin v1.0.0
```

The `Release` workflow builds and smoke-tests native bundles for Linux x86_64,
Windows x86_64, macOS Intel and macOS Apple Silicon, then attaches them to the
GitHub release. You do not need to create the release manually.

To test the build without publishing, run the `Release` workflow manually with
`workflow_dispatch`; the build jobs run, but the release job is skipped because
the ref is not a tag.

## 4. After publishing

- Confirm both the CI matrix and the release build are green.
- Confirm the release has four platform archives.
- Keep `requirements.txt`, `requirements-build.txt`, and the workflows aligned.
- Do not force-add the APK. It is proprietary and intentionally excluded.
- Hardware validation reports belong in GitHub issues; see
  `CONTRIBUTING.md`.
- Release binaries are unsigned; see `BUILDING.md` for signing caveats.
