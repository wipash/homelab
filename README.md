# SK Homelab



brew install helm



### Flux
Create a GitHub API token, check all repo permissions and `admin:public_key`
Create a GitHub repo for flux

```bash
brew install fluxcd/tap/flux

flux bootstrap github \
  --owner=wipash \
  --repository=wipash/homelab-flux \
  --personal
```

### SOPS
Copy age master key to ~/.config/sops/age/keys.txt

Edit a secret:
`sops sops-test-secret-encrypted.yaml`

Encrypt a secret:
`sops -e global-secrets.dec.yaml | tee global-secrets.yaml`

Make a secret:
`kubectl create secret generic sopstest --from-literal=foo=bar -o yaml --dry-run=client | tee sops-test-secret.yaml`

