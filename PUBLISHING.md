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
gh release create v1.0.0 --generate-notes
```

The release contains GitHub's source archives. No binary is attached because
the application runs directly from source.

## 4. After publishing

- Confirm the CI check is green.
- Add the repository URL to `README.md` if you want an explicit clone command.
- Keep `requirements.txt` and `.github/workflows/ci.yml` aligned.
- Do not force-add the APK. It is proprietary and intentionally excluded.
- Hardware validation reports belong in GitHub issues; see
  `CONTRIBUTING.md`.
