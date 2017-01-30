{ system ? builtins.currentSystem, size ? "10", pkgs ? import <nixpkgs> {} }:
let
  base_image = import ./generic-image.nix {
    inherit system size;
    extraConfig = { pkgs, ... }: {
      # Support for VMWare paravirtual SCSI adapter is required to detect root drive
      boot.initrd.availableKernelModules = [ "vmw_pvscsi" ];

      # Guest services are required to detect IP address and deploy SSH keys
      services.vmwareGuest.enable = true;

      # Deploy SSH host keys and authorized keys
      systemd.services.get-nixops-ssh-keys = {
        description = "Get NixOps SSH Key";
        wantedBy = [ "multi-user.target" ];
        before = [ "sshd.service" ];
        requires = [ "vmware.service" ];
        after = [ "vmware.service" ];
        script = ''
          set -o pipefail

          mkdir -p /etc/ssh/authorized_keys.d
          ${pkgs.open-vm-tools}/bin/vmtoolsd --cmd "info-get guestinfo.sshAuthorizedKeys" > /etc/ssh/authorized_keys.d/root
          ${pkgs.open-vm-tools}/bin/vmtoolsd --cmd "info-get guestinfo.sshPrivateHostKey" > /etc/ssh/ssh_host_ed25519_key
          chmod 0600 /etc/ssh/ssh_host_ed25519_key
          ${pkgs.open-vm-tools}/bin/vmtoolsd --cmd "info-get guestinfo.sshPublicHostKey" > /etc/ssh/ssh_host_ed25519_key.pub
        '';
      };
    };
  };
in pkgs.runCommand "vsphere-image" {} ''
  # Convert to VMDK after the image has been prepared because QEMU can't handle stream-optimized VMDKs
  # but ESXi refuses to import other VMDK types
  echo "converting image to VDMK..."
  mkdir $out
  ${pkgs.vmTools.qemu}/bin/qemu-img convert -f qcow2 -O vmdk \
    -o subformat=streamOptimized,compat6 ${base_image}/disk.qcow2 $out/disk.vmdk
''