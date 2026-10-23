# Releasing to PyPI

The `Release` workflow (`.github/workflows/release.yml`) publishes kroger-mcp to PyPI through
[trusted publishing](https://docs.pypi.org/trusted-publishers/). For each release, PyPI gives the workflow
a token that is valid for one upload and expires within 15 minutes, so no PyPI API token is stored in the
repository, in GitHub secrets, or on a maintainer's computer.

## Release a new version

1. If this release needs a new kroger-api version, release kroger-api first and wait until
   `pip install kroger-api==<version>` works, then raise the `kroger-api` floor in `pyproject.toml` and
   run `uv lock --refresh --upgrade-package kroger-api`. The lowest-versions test installs that floor
   from PyPI, so it fails until kroger-api is published.
2. Update `version` in `pyproject.toml` and add the release notes to `CHANGELOG.md`. Merge to `main`.
3. Tag the merge commit and push the tag. Only the repository owner can create `v*` tags:

   ```bash
   git tag v0.5.0
   git push origin v0.5.0
   ```

4. The workflow then:
   - builds the sdist and wheel with the build backend pinned in `.github/build-constraints.txt`;
   - stops if the tag is not `v` followed by the package version;
   - runs the test suite against those exact files on Linux and Windows, on the oldest and newest
     supported Python, and with every dependency at the lowest version `pyproject.toml` allows;
   - waits for approval in the `pypi` environment.
5. Open the run in the Actions tab, select **Review deployments**, and approve `pypi`. The publish job
   uploads the files and their signed [attestations](https://docs.pypi.org/attestations/).
6. Create the GitHub release from the changelog section:

   ```bash
   awk '/^## \[0.5.0\]/{f=1;next} /^## \[/{f=0} f' CHANGELOG.md > notes.md
   gh release create v0.5.0 --title v0.5.0 --notes-file notes.md
   ```

To test the built files locally before you tag, run the same commands as the `Tests` workflow
(`.github/workflows/tests.yml`).

## Who can publish

Anyone with write access to the repository can change `release.yml`, so the workflow file cannot limit who
publishes. These settings do. Only the repository owner can change them.

| Where | Setting |
|---|---|
| Settings > Environments > `pypi` | Required reviewer: the repository owner. "Prevent self-review" is off, because the owner both pushes the tag and approves. Deployment branches and tags: one rule, type **Tag**, pattern `v*`. |
| Settings > Rules > Rulesets | Tag ruleset on `refs/tags/v*`: restrict creations, updates and deletions; block force pushes; bypass list: the repository owner only. |
| Settings > Rules > Rulesets | Branch ruleset on `main`: require a pull request with one approval; block force pushes; bypass list: the repository owner only. |
| Settings > Actions > General | Require approval for workflow runs from all outside contributors. |
| PyPI > kroger-mcp > Publishing | One GitHub publisher: owner `CupOfOwls`, repository `kroger-mcp`, workflow `release.yml`, environment `pypi`. |

The environment name on the PyPI publisher is required. A publisher without one accepts a token from any
environment, or from no environment, so the environment rules above would not apply.

To check the settings:

```bash
gh api repos/CupOfOwls/kroger-mcp/environments/pypi
gh api repos/CupOfOwls/kroger-mcp/environments/pypi/deployment-branch-policies
gh api repos/CupOfOwls/kroger-mcp/rulesets
```

and open the project's **Publishing** page on PyPI.

## Changing the workflows

- Do not add `workflow_dispatch`, `pull_request_target`, or a cache to `release.yml`. The build and
  publish jobs must not restore a cache, because a cache written by another workflow could change what
  gets built.
- Only the publish job has `id-token: write`. Keep the build in its own job.
- Actions are pinned to full commit SHAs, with the version in a comment. To update one, find the commit
  of the new tag (an annotated tag points to a tag object, so read that object to get the commit) and
  prefer a release that is at least two weeks old.
- To change the build backend, regenerate `.github/build-constraints.txt` with the command in its header.
