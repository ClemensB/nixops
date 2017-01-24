{ config, pkgs, lib, ... }:

with lib;

let
  sz = toString config.deployment.vsphere.baseImageSize;
  base_image = import ./generic-image.nix {
    size = sz;
    extraConfig = {
      boot.initrd.availableKernelModules = [ "vmw_pvscsi" ];
      services.vmwareGuest.enable = true;
    };
  };
  the_key = builtins.getEnv "NIXOPS_VSPHERE_PUBKEY";
  ssh_image = pkgs.vmTools.runInLinuxVM (
    pkgs.runCommand "vsphere-ssh-image"
      { memSize = 768;
        preVM =
          ''
            mkdir $out
            diskImage=$out/image
            ${pkgs.vmTools.qemu}/bin/qemu-img create -f qcow2 -b ${base_image}/disk.vmdk $diskImage
          '';
        buildInputs = [ pkgs.utillinux ];
        postVM =
          ''
            # Convert to VMDK after VM because QEMU can't handle stream-optimized VMDKs
            ${pkgs.vmTools.qemu}/bin/qemu-img convert -f qcow2 -O vmdk \
              -o subformat=streamOptimized,compat6 \
              $diskImage $out/disk.vmdk
            rm $diskImage
          '';
      }
      ''
        . /sys/class/block/vda1/uevent
        mknod /dev/vda1 b $MAJOR $MINOR
        mkdir /mnt
        mount /dev/vda1 /mnt

        mkdir -p /mnt/etc/ssh/authorized_keys.d
        echo '${the_key}' > /mnt/etc/ssh/authorized_keys.d/root
        umount /mnt
      ''
  );
in

{

  ###### interface

  options = {
    deployment.vsphere.host = mkOption {
      type = types.str;
      description = ''
        Hostname of the vSphere service to connect to.
      '';
    };

    deployment.vsphere.port = mkOption {
      type = types.int;
      default = 443;
      description = ''
        Port of the vSphere service to connect to.
      '';
    };

    deployment.vsphere.user = mkOption {
      type = types.str;
      default = "root";
      description = ''
        Username used for authentication on the vSphere service.
      '';
    };

    deployment.vsphere.password = mkOption {
      type = types.str;
      description = ''
        Password used for authentication on the vSphere service.
      '';
    };

    deployment.vsphere.datacenter = mkOption {
      type = with types; nullOr str;
      default = null;
      description = ''
        Name of the datacenter which sould be used.
        If this is null, the first datacenter found will be used.
      '';
    };

    deployment.vsphere.datastore = mkOption {
      type = with types; nullOr str;
      default = null;
      description = ''
        Name of the datastore where the VM should be deployed to.
        If this is null, the first datastore found will be used.
      '';
    };

    deployment.vsphere.cluster = mkOption {
      type = with types; nullOr str;
      default = null;
      description = ''
        Name of the cluster where the VM should be deployed to.
        If this is null, the first cluster found will be used.
      '';
    };

    deployment.vsphere.vcpu = mkOption {
      default = 1;
      type = types.int;
      description = ''
        Number of Virtual CPUs.
      '';
    };

    deployment.vsphere.memorySize = mkOption {
      default = 512;
      type = types.int;
      description = ''
        Memory size (M) of virtual machine.
      '';
    };

    deployment.vsphere.baseImageSize = mkOption {
      default = 10;
      type = types.int;
      description = ''
        The size (G) of base image of virtual machine.
      '';
    };

    deployment.vsphere.baseImage = mkOption {
      default = null;
      example = "/home/alice/base-disk.vmdk";
      type = with types; nullOr path;
      description = ''
        The disk is created using the specified
        disk image as a base.
      '';
    };

    deployment.vsphere.networks = mkOption {
      type = types.listOf types.str;
      description = "Names of port groups to attach the VM to.";
    };
  };

  ###### implementation

  config = mkIf (config.deployment.targetEnv == "vsphere") {
    deployment.vsphere.baseImage = mkDefault ssh_image;

    nixpkgs.system = mkOverride 900 "x86_64-linux";

    fileSystems."/".device = "/dev/disk/by-label/nixos";

    boot.loader.grub.version = 2;
    boot.loader.grub.device = "/dev/sda";
    boot.loader.timeout = 0;

    services.openssh.enable = true;
    services.openssh.startWhenNeeded = false;
    services.openssh.extraConfig = "UseDNS no";

    deployment.hasFastConnection = true;
};

}
