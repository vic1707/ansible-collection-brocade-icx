# vic1707.icx

An unofficial Ansible collection for Brocade ICX switches.

- [Installation and usage](ansible_collections/vic1707/icx/README.md)
- [Example playbooks](example_playbooks)

## Publishing

Set `GALAXY_API_KEY` in repository secrets. Update the collection's `galaxy.yml`
version and `CHANGELOG.md`, merge to `main`, then tag that commit and push:

```sh
git tag -a v1.0.0 -m "Release 1.0.0"
git push origin v1.0.0
```

CI runs tests and lint, builds the collection and publishes it to Galaxy.
No GitHub Release is required. Update module docs alongside code changes.
