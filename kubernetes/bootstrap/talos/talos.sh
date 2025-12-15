#!/usr/bin/bash


# talhelper gensecret --patch-configfile > talenv.sops.yaml
# sops -e -i talenv.sops.yaml
talhelper genconfig



# talosctl --talosconfig=./talos/talosconfig config endpoint 10.0.16.132
talosctl config merge ./clusterconfig/talosconfig

echo "Applying to hp1"
talosctl apply-config --insecure --nodes 10.0.16.133 --file "$(find ./clusterconfig -name "*hp1*")"

echo "Applying to hp2"
talosctl apply-config --insecure --nodes 10.0.16.135 --file "$(find ./clusterconfig -name "*hp2*")"

echo "Applying to hp3"
talosctl apply-config --insecure --nodes 10.0.16.136 --file "$(find ./clusterconfig -name "*hp3*")"

echo "Waiting 2 mins"
sleep 120

echo "Bootstrapping cluster"
talosctl bootstrap -n 10.0.16.133

echo "Waiting 3 mins"
sleep 180

talosctl kubeconfig

# Not needed anymore, talos config should do this automatically
# kubectl apply -f ./cilium/quick-install.yaml
