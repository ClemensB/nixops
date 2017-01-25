{
  pkgs ? import <nixpkgs> {},
  system ? builtins.currentSystem,
  size ? "10",
  authorizedSSHKeys
}:
let
  base_image = import ./generic-image.nix {
    inherit size;
    extraConfig = {
      # Support for VMWare paravirtual SCSI adapter is required to detect root drive
      boot.initrd.availableKernelModules = [ "vmw_pvscsi" ];

      # Guest services are required to detect IP address
      services.vmwareGuest.enable = true;
    };
  };
in
pkgs.vmTools.runInLinuxVM (
  pkgs.runCommand "vsphere-ssh-image" {
    memSize = 768;
    preVM =
      ''
        diskImage=image
        ${pkgs.vmTools.qemu}/bin/qemu-img create -f qcow2 -b ${base_image}/disk.qcow2 $diskImage
      '';
    buildInputs = [ pkgs.utillinux ];
    postVM =
      ''
        # Convert to VMDK after VM because QEMU can't handle stream-optimized VMDKs
        # but ESXi refuses to accept other VMDK types
        echo "converting image to VDMK..."
        ${pkgs.vmTools.qemu}/bin/qemu-img convert -f qcow2 -O vmdk \
          -o subformat=streamOptimized,compat6 $diskImage $out/disk.vmdk
          rm $diskImage
      '';
  }
  ''
    . /sys/class/block/vda1/uevent
    mknod /dev/vda1 b $MAJOR $MINOR
    mkdir /mnt
    mount /dev/vda1 /mnt

    mkdir -p /mnt/etc/ssh/authorized_keys.d
    echo '${authorizedSSHKeys}' > /mnt/etc/ssh/authorized_keys.d/root
    umount /mnt
  ''
)