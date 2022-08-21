#!/usr/bin/bash


# talhelper gensecret --patch-configfile > talenv.sops.yaml
# sops -e -i talenv.sops.yaml
talhelper genconfig



talosctl config node 10.0.16.131
talosctl config endpoint 10.0.16.131

echo "Applying to master"
talosctl apply-config --insecure --nodes 10.0.16.131 --file "$(find ./clusterconfig -name "*nuc1*")"

echo "Applying to worker"
#

echo "Waiting 2 mins"
sleep 120

echo "Bootstrapping cluster"
talosctl bootstrap

echo "Waiting 3 mins"
sleep 180

talosctl kubeconfig
