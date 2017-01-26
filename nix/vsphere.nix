{ config, pkgs, lib, ... }:

with lib;

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


    deployment.vsphere.networks = mkOption {
      type = types.listOf types.str;
      description = "Names of port groups to attach the VM to.";
    };
  };

  ###### implementation

  config = mkIf (config.deployment.targetEnv == "vsphere") {
    nixpkgs.system = mkOverride 900 "x86_64-linux";

    fileSystems."/".device = "/dev/disk/by-label/nixos";

    boot.loader.grub.version = 2;
    boot.loader.grub.device = "/dev/sda";
    boot.loader.timeout = 0;

    # Support for VMWare paravirtual SCSI adapter is required to detect root drive
    boot.initrd.availableKernelModules = [ "vmw_pvscsi" ];

    services.openssh.enable = true;
    services.openssh.startWhenNeeded = false;
    services.openssh.extraConfig = "UseDNS no";

    # Guest services are required to detect IP address
    services.vmwareGuest.enable = true;

    deployment.hasFastConnection = true;
};

}
