#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Boots the Android VM on a plain k3d + KubeVirt cluster and checks it the way
# the driver will: adb over the pod network, boot completed, cluster DNS,
# GLES, and a screenshot. Writes evidence to ${OUT}.
set -euo pipefail

IMAGE=${IMAGE:?containerDisk image}
OUT=${OUT:-out}
NS=${NS:-atak}
mkdir -p "${OUT}"

kubectl create namespace "${NS}" --dry-run=client -o yaml | kubectl apply -f -
cat <<YAML | kubectl apply -n "${NS}" -f -
apiVersion: kubevirt.io/v1
kind: VirtualMachine
metadata:
  name: atak-device
spec:
  runStrategy: Always
  template:
    metadata:
      labels:
        app.kubernetes.io/name: atak-device
    spec:
      domain:
        cpu: {cores: 2}
        memory: {guest: 3Gi}
        firmware:
          kernelBoot:
            container:
              image: ${IMAGE}
              imagePullPolicy: IfNotPresent
              kernelPath: /boot/kernel
              initrdPath: /boot/initrd.img
            kernelArgs: "root=/dev/ram0 SRC=/android androidboot.selinux=permissive console=ttyS0 video=720x1280 quiet"
        devices:
          logSerialConsole: true
          disks:
            - name: android
              disk: {bus: virtio}
          interfaces:
            - name: default
              masquerade: {}
              ports:
                - {name: adb, port: 5555}
      networks:
        - name: default
          pod: {}
      volumes:
        - name: android
          containerDisk:
            image: ${IMAGE}
            imagePullPolicy: IfNotPresent
            path: /disk/android.qcow2
YAML

start=$(date +%s)
until kubectl get vmi -n "${NS}" atak-device >/dev/null 2>&1; do sleep 2; done
kubectl wait vmi -n "${NS}" atak-device --for condition=Ready --timeout=10m
echo "vmi ready after $(( $(date +%s) - start ))s"
ip="$(kubectl get vmi -n "${NS}" atak-device -o jsonpath='{.status.interfaces[0].ipAddress}')"
echo "vmi ip ${ip}"

kubectl run adb -n "${NS}" --image=ubuntu:24.04 --restart=Never --command -- sleep infinity
kubectl wait pod -n "${NS}" adb --for condition=Ready --timeout=5m
kubectl exec -n "${NS}" adb -- bash -c 'apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq adb >/dev/null'

a() { kubectl exec -n "${NS}" adb -- adb -s "${ip}:5555" "$@"; }
for _ in $(seq 1 90); do
  kubectl exec -n "${NS}" adb -- adb connect "${ip}:5555" >/dev/null 2>&1 || true
  if [ "$(a shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ]; then break; fi
  sleep 5
done
echo "boot completed after $(( $(date +%s) - start ))s"
{
  echo "release: $(a shell getprop ro.build.version.release)"
  echo "sdk: $(a shell getprop ro.build.version.sdk)"
  echo "abilist: $(a shell getprop ro.product.cpu.abilist)"
  echo "wm size: $(a shell wm size)"
  echo "dns1: $(a shell getprop net.dns1)"
  echo "kubernetes.default lookup:"; a shell ping -c1 -W2 kubernetes.default.svc.cluster.local || true
  echo "GLES:"; a shell dumpsys SurfaceFlinger | grep -i -E 'GLES|OpenGL' || true
} | tee "${OUT}/device.txt"
a shell screencap -p /sdcard/s.png
kubectl exec -n "${NS}" adb -- adb -s "${ip}:5555" pull /sdcard/s.png /tmp/s.png
kubectl cp "${NS}/adb:/tmp/s.png" "${OUT}/android-home.png"
ls -la "${OUT}"
