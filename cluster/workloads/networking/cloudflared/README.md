# Cloudflare Argo tunnel

To create tunnel:

```
cloudflared tunnel login
cloudflared tunnel create k3s-homelab-0
cloudflared tunnel route dns k3s-homelab-0 tunnel.mydomainname.com
```

Route a service to the tunnel by adding annotations:
```
ingress:
    annotations:
        external-dns/is-public: "true"
        external-dns.alpha.kubernetes.io/target: "tunnel.${SECRET_DOMAIN}"
```
