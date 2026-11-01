# vic1707.icx

An unofficial Ansible collection for Brocade ICX switches.

- [Installation and usage](ansible_collections/vic1707/icx/README.md)
- [Example playbooks](example_playbooks)

## Publishing

Set `GALAXY_API_KEY` in repository secrets. Update the collection's `galaxy.yml`
version and `CHANGELOG.md`, then tag the commit to publish and push:

```sh
git tag -a v0.1.0 -m "Release 0.1.0"
git push origin v0.1.0
```

CI runs tests and lint, builds the collection and publishes it to Galaxy.
No GitHub Release is required. Update module docs alongside code changes.

Prerelease tags such as `v0.1.1-experimental.1` work too; set `galaxy.yml` version
to `0.1.1-experimental.1`. Install explicitly with
`ansible-galaxy collection install vic1707.icx:==0.1.1-experimental.1`.
