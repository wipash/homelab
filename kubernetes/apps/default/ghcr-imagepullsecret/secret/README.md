# Create a dockerconfigjson secret:
1. Build an auth string with your username and PAT:
```bash
echo -n "username:123123adsfasdf123123" | base64
```

2. Put that into a docker config.json format:
```json
{
    "auths":
    {
        "ghcr.io":
            {
                "auth":"xxxxxxxxxxxxxxxxxxx="
            }
    }
}
```

3. Use that as your secret:
```json
{"auths":{"ghcr.io":{"auth":"xxxxxxxxxxxxxxxxxxx="}}}
```
