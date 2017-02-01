# -*- coding: utf-8 -*-
import atexit
import os
import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom
import StringIO
import time

import requests

from pyVim import connect
from pyVmomi import vim

import nixops.known_hosts
import nixops.util
from nixops.backends import MachineDefinition, MachineState

_namespaces = {
    'cim': 'http://schemas.dmtf.org/wbem/wscim/1/common',
    'ovf': 'http://schemas.dmtf.org/ovf/envelope/1',
    'rasd': 'http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData',
    'vmw': 'http://www.vmware.com/schema/ovf',
    'vssd': 'http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_VirtualSystemSettingData',
    'xsi': 'http://www.w3.org/2001/XMLSchema-instance'
}


def _sub_element_ns(parent, ns_prefix, tag):
    return ET.SubElement(parent, '{%s}%s' % (_namespaces[ns_prefix], tag))


def _set_attr_ns(elem, ns_prefix, attrib, value):
    elem.set('{%s}%s' % (_namespaces[ns_prefix], attrib), value)


def _add_vmw_config(parent, key, value):
    config_element = _sub_element_ns(parent, 'vmw', 'Config')
    _set_attr_ns(config_element, 'ovf', 'required', 'false')
    _set_attr_ns(config_element, 'vmw', 'key', key)
    _set_attr_ns(config_element, 'vmw', 'value', value)


for prefix, uri in _namespaces.iteritems():
    ET.register_namespace(prefix, uri)


class VirtualSystemBuilder(object):
    def __init__(self, root):
        self.root = root
        self.instance_id = 0

        # Counters just used for naming things
        self.num_cd_rom = 1
        self.num_hard_drive = 1
        self.num_floppy_drive = 1
        self.num_ethernet = 1

        self.virtual_hardware_section = ET.SubElement(self.root, 'VirtualHardwareSection')
        ET.SubElement(self.virtual_hardware_section, 'Info').text = 'Virtual hardware requirements'

    def _new_instance_id(self):
        self.instance_id += 1
        return self.instance_id - 1

    def _new_cd_rom_num(self):
        self.num_cd_rom += 1
        return self.num_cd_rom - 1

    def _new_hard_drive_num(self):
        self.num_hard_drive += 1
        return self.num_hard_drive - 1

    def _new_floppy_drive_num(self):
        self.num_floppy_drive += 1
        return self.num_floppy_drive - 1

    def _new_ethernet_num(self):
        self.num_ethernet += 1
        return self.num_ethernet - 1

    def add_operating_system_section(self, os_id, os_type):
        operating_system_section = ET.SubElement(self.root, 'OperatingSystemSection')
        _set_attr_ns(operating_system_section, 'ovf', 'id', str(os_id))
        _set_attr_ns(operating_system_section, 'vmw', 'osType', os_type)
        ET.SubElement(operating_system_section, 'Info').text = 'The kind of installed guest operating system'

    def _add_setting_data(self, ns, tag, name):
        item = ET.SubElement(self.virtual_hardware_section, tag)
        _sub_element_ns(item, ns, 'ElementName').text = name
        instance_id = self._new_instance_id()
        _sub_element_ns(item, ns, 'InstanceID').text = str(instance_id)
        return item, instance_id

    def _add_virtual_system_setting_data(self, name, resource_type):
        item, instance_id = self._add_setting_data('rasd', 'Item', name)
        _sub_element_ns(item, 'rasd', 'ResourceType').text = str(resource_type)
        return item, instance_id

    def add_hardware_system(self, system_name, system_type):
        system, instance_id = self._add_setting_data('vssd', 'System', 'Virtual Hardware Family')
        _sub_element_ns(system, 'vssd', 'VirtualSystemIdentifier').text = system_name
        _sub_element_ns(system, 'vssd', 'VirtualSystemType').text = system_type
        return instance_id

    def add_hardware_vcpus(self, num_vcpus):
        vcpus, instance_id = self._add_virtual_system_setting_data('%d virtual CPU(s)' % num_vcpus, 3)
        _sub_element_ns(vcpus, 'rasd', 'AllocationUnits').text = 'hertz * 10^6'
        _sub_element_ns(vcpus, 'rasd', 'Description').text = 'Number of Virtual CPUs'
        _sub_element_ns(vcpus, 'rasd', 'VirtualQuantity').text = str(num_vcpus)
        cores_per_socket = _sub_element_ns(vcpus, 'vmw', 'CoresPerSocket')
        cores_per_socket.text = str(num_vcpus)
        _set_attr_ns(cores_per_socket, 'ovf', 'required', 'false')
        return instance_id

    def add_hardware_memory(self, memory_mb):
        memory, instance_id = self._add_virtual_system_setting_data('%dMB of memory' % memory_mb, 4)
        _sub_element_ns(memory, 'rasd', 'AllocationUnits').text = 'byte * 2^20'
        _sub_element_ns(memory, 'rasd', 'Description').text = 'Memory Size'
        _sub_element_ns(memory, 'rasd', 'VirtualQuantity').text = str(memory_mb)
        return instance_id

    def add_hardware_sata_controller(self, address):
        sata_ctrl, instance_id = self._add_virtual_system_setting_data('SATA Controller %d' % address, 20)
        _sub_element_ns(sata_ctrl, 'rasd', 'Address').text = str(address)
        _sub_element_ns(sata_ctrl, 'rasd', 'Description').text = 'SATA Controller'
        _sub_element_ns(sata_ctrl, 'rasd', 'ResourceSubType').text = 'vmware.sata.ahci'
        return instance_id

    def add_hardware_scsi_controller(self, address):
        scsi_ctrl, instance_id = self._add_virtual_system_setting_data('SCSI Controller %d' % address, 6)
        _sub_element_ns(scsi_ctrl, 'rasd', 'Address').text = str(address)
        _sub_element_ns(scsi_ctrl, 'rasd', 'Description').text = 'SCSI Controller'
        _sub_element_ns(scsi_ctrl, 'rasd', 'ResourceSubType').text = 'VirtualSCSI'
        return instance_id

    def add_hardware_usb_controller(self, address):
        usb_ctrl, instance_id = self._add_virtual_system_setting_data('USB Controller', 23)
        _set_attr_ns(usb_ctrl, 'ovf', 'required', 'false')
        _sub_element_ns(usb_ctrl, 'rasd', 'Address').text = str(address)
        _sub_element_ns(usb_ctrl, 'rasd', 'Description').text = 'USB Controller (EHCI)'
        _sub_element_ns(usb_ctrl, 'rasd', 'ResourceSubType').text = 'vmware.usb.ehci'
        _add_vmw_config(usb_ctrl, 'autoConnectDevices', 'false')
        _add_vmw_config(usb_ctrl, 'ehciEnabled', 'true')
        return instance_id

    def add_hardware_ide_controller(self, address):
        ide_ctrl, instance_id = self._add_virtual_system_setting_data('VirtualIDEController %d' % address, 5)
        _sub_element_ns(ide_ctrl, 'rasd', 'Address').text = str(address)
        _sub_element_ns(ide_ctrl, 'rasd', 'Description').text = 'IDE Controller'
        return instance_id

    def add_hardware_video_card(self, enable_3d_support, enable_mpt_support, use_3d_renderer, use_auto_detect,
                                video_ram_size_in_kb):
        video_card, instance_id = self._add_virtual_system_setting_data('VirtualVideoCard', 24)
        _set_attr_ns(video_card, 'ovf', 'required', 'false')
        _sub_element_ns(video_card, 'rasd', 'AutomaticAllocation').text = 'false'
        _add_vmw_config(video_card, 'enable3DSupport', 'true' if enable_3d_support else 'false')
        _add_vmw_config(video_card, 'enableMPTSupport', 'true' if enable_mpt_support else 'false')  # What's this?
        _add_vmw_config(video_card, 'use3dRenderer', use_3d_renderer)
        _add_vmw_config(video_card, 'useAutoDetect', 'true' if use_auto_detect else 'false')
        _add_vmw_config(video_card, 'videoRamSizeInKB', str(video_ram_size_in_kb))
        return instance_id

    def add_hardware_vmci_device(self, allow_unrestricted_communication):
        vmci_device, instance_id = self._add_virtual_system_setting_data('VirtualVMCIDevice', 1)
        _set_attr_ns(vmci_device, 'ovf', 'required', 'false')
        _sub_element_ns(vmci_device, 'rasd', 'AutomaticAllocation').text = 'false'
        _sub_element_ns(vmci_device, 'rasd', 'ResourceSubType').text = 'vmware.vmci'
        _add_vmw_config(vmci_device, 'allowUnrestrictedCommunication',
                        'true' if allow_unrestricted_communication else 'false')
        return instance_id

    def add_hardware_cd_rom(self, parent, address_on_parent):
        cd_rom, instance_id = self._add_virtual_system_setting_data('CD-ROM %d' % self._new_cd_rom_num(), 15)
        _set_attr_ns(cd_rom, 'ovf', 'required', 'false')
        _sub_element_ns(cd_rom, 'rasd', 'AddressOnParent').text = str(address_on_parent)
        _sub_element_ns(cd_rom, 'rasd', 'AutomaticAllocation').text = 'false'
        _sub_element_ns(cd_rom, 'rasd', 'ResourceSubType').text = 'vmware.cdrom.atapi'
        _sub_element_ns(cd_rom, 'rasd', 'Parent').text = str(parent)
        return instance_id

    def add_hardware_hard_disk(self, parent, address_on_parent, host_resource, write_through, disk_mode=None):
        hard_disk, instance_id = self._add_virtual_system_setting_data('Hard Disk %d' % self._new_hard_drive_num(), 17)
        _sub_element_ns(hard_disk, 'rasd', 'AddressOnParent').text = str(address_on_parent)
        _sub_element_ns(hard_disk, 'rasd', 'Parent').text = str(parent)
        _sub_element_ns(hard_disk, 'rasd', 'HostResource').text = host_resource
        _add_vmw_config(hard_disk, 'backing.writeThrough', 'true' if write_through else 'false')
        if disk_mode is not None:
            _add_vmw_config(hard_disk, 'backing.diskMode', disk_mode)
        return instance_id

    def add_hardware_floppy_drive(self, address_on_parent):
        floppy, instance_id = self._add_virtual_system_setting_data('Floppy %d' % self._new_floppy_drive_num(), 14)
        _set_attr_ns(floppy, 'ovf', 'required', 'false')
        _sub_element_ns(floppy, 'rasd', 'AddressOnParent').text = str(address_on_parent)
        _sub_element_ns(floppy, 'rasd', 'AutomaticAllocation').text = 'false'
        _sub_element_ns(floppy, 'rasd', 'Description').text = 'Floppy Drive'
        _sub_element_ns(floppy, 'rasd', 'ResourceSubType').text = 'vmware.floppy.remotedevice'
        return instance_id

    def add_hardware_ethernet(self, address_on_parent, connection, adapter_type, wake_on_lan_enabled):
        ethernet, instance_id = self._add_virtual_system_setting_data('Ethernet %d' % self._new_ethernet_num(), 10)
        _set_attr_ns(ethernet, 'ovf', 'required', 'false')
        _sub_element_ns(ethernet, 'rasd', 'AddressOnParent').text = str(address_on_parent)
        _sub_element_ns(ethernet, 'rasd', 'AutomaticAllocation').text = 'true'
        _sub_element_ns(ethernet, 'rasd', 'Connection').text = connection
        _sub_element_ns(ethernet, 'rasd', 'Description').text = \
            '%s ethernet adapter on &quot;%s&quot;' % (adapter_type, connection)
        _sub_element_ns(ethernet, 'rasd', 'ResourceSubType').text = adapter_type
        _add_vmw_config(ethernet, 'wakeOnLanEnabled', 'true' if wake_on_lan_enabled else 'false')
        return instance_id

    def add_vmw_config(self, key, value):
        _add_vmw_config(self.virtual_hardware_section, key, value)


class OVFBuilder(object):
    def __init__(self):
        self.root = ET.Element('Envelope')
        self.root.set('xmlns', _namespaces['ovf'])
        self.tree = ET.ElementTree(self.root)

        self.references = ET.SubElement(self.root, 'References')

        self.disk_section = ET.SubElement(self.root, 'DiskSection')
        ET.SubElement(self.disk_section, 'Info').text = 'Virtual disk information'

        self.network_section = ET.SubElement(self.root, 'NetworkSection')
        ET.SubElement(self.network_section, 'Info').text = 'The list of logical networks'

    def add_file_reference(self, href, reference_id, size):
        file_reference = ET.SubElement(self.references, 'File')
        _set_attr_ns(file_reference, 'ovf', 'href', href)
        _set_attr_ns(file_reference, 'ovf', 'id', reference_id)
        _set_attr_ns(file_reference, 'ovf', 'size', str(size))

    def add_disk(self, capacity, capacity_allocation_units, disk_id, file_ref, disk_format):
        disk = ET.SubElement(self.disk_section, 'Disk')
        _set_attr_ns(disk, 'ovf', 'capacity', str(capacity))
        _set_attr_ns(disk, 'ovf', 'capacityAllocationUnits', capacity_allocation_units)
        _set_attr_ns(disk, 'ovf', 'diskId', disk_id)
        _set_attr_ns(disk, 'ovf', 'fileRef', file_ref)
        _set_attr_ns(disk, 'ovf', 'format', disk_format)

    def add_network(self, name):
        network = ET.SubElement(self.network_section, 'Network')
        _set_attr_ns(network, 'ovf', 'name', name)
        ET.SubElement(network, 'Description').text = 'The %s network' % name

    def add_virtual_system(self, system_name):
        virtual_system = ET.SubElement(self.root, 'VirtualSystem')
        _set_attr_ns(virtual_system, 'ovf', 'id', system_name)
        ET.SubElement(virtual_system, 'Info').text = 'A virtual machine'
        ET.SubElement(virtual_system, 'Name').text = system_name
        return VirtualSystemBuilder(virtual_system)

    def get_xml(self):
        # Sort rasd:* elements because that's required by definition
        for vm in self.root.findall('VirtualSystem'):
            for item in vm.find('VirtualHardwareSection').findall('Item'):
                item[:] = sorted(item, key=lambda child: child.tag)

        xml_file = StringIO.StringIO()
        self.tree.write(xml_file, encoding="utf-8", xml_declaration=True)
        xml_str = xml_file.getvalue()
        xml_file.close()

        # Pretty print OVF XML
        return minidom.parseString(xml_str).toprettyxml(indent='    ')


def generate_simple_ovf(name, num_vcpus, memory_mb, disk_capacity_mb, networks):
    ovf = OVFBuilder()

    ovf.add_file_reference('disk-1.vmdk', 'file1', 0)
    ovf.add_disk(disk_capacity_mb, 'byte * 2^20', 'vmdisk1', 'file1',
                 'http://www.vmware.com/interfaces/specifications/vmdk.html#streamOptimized')

    for network in networks:
        ovf.add_network(network)

    system = ovf.add_virtual_system(name)
    system.add_operating_system_section(100, 'other3xLinux64Guest')
    system.add_hardware_system(name, 'vmx-11')
    system.add_hardware_vcpus(num_vcpus)
    system.add_hardware_memory(memory_mb)
    scsi_ctrl = system.add_hardware_scsi_controller(0)
    system.add_hardware_video_card(False, False, 'automatic', False, 4096)
    system.add_hardware_vmci_device(False)
    system.add_hardware_hard_disk(scsi_ctrl, 0, 'ovf:/disk/vmdisk1', False)

    nic_address_on_parent = 7  # For some reason it starts with 7
    for network in networks:
        system.add_hardware_ethernet(nic_address_on_parent, network, 'VmxNet3', True)
        nic_address_on_parent += 1

    return ovf.get_xml()


class VSphereDefinition(MachineDefinition):
    """ Definition of a VSphere machine. """

    @classmethod
    def get_type(cls):
        return "vsphere"

    def __init__(self, xml, config):
        MachineDefinition.__init__(self, xml, config)


class ReadFileMonitor(file):
    def __init__(self, name, mode='r', buffering=-1, callback=None, *args):
        super(ReadFileMonitor, self).__init__(name, mode, buffering)
        self.seek(0, os.SEEK_END)
        self._length = self.tell()
        self.seek(0)
        self._callback = callback
        self._args = args

    def __len__(self):
        return self._length

    def read(self, size=-1):
        data = super(ReadFileMonitor, self).read(size)
        self._callback(self._length, self.tell(), *self._args)
        return data


class VSphereState(MachineState):
    client_public_key = nixops.util.attr_property("vsphere.clientPublicKey", None)
    client_private_key = nixops.util.attr_property("vsphere.clientPrivateKey", None)

    host_public_key = nixops.util.attr_property("vsphere.hostPublicKey", None)
    host_private_key = nixops.util.attr_property("vsphere.hostPrivateKey", None)

    # vSphere credentials
    vsphere_host = nixops.util.attr_property("vsphere.host", None)
    vsphere_port = nixops.util.attr_property("vsphere.port", None, int)
    vsphere_user = nixops.util.attr_property("vsphere.user", None)
    vsphere_password = nixops.util.attr_property("vsphere.password", None)

    ip_address = nixops.util.attr_property("vsphere.ipAddress", None)

    @property
    def private_ipv4(self):
        return self.ip_address

    @property
    def public_host_key(self):
        return self.host_public_key

    @property
    def resource_id(self):
        return self.vm_id

    @classmethod
    def get_type(cls):
        return "vsphere"

    def __init__(self, depl, name, id):
        MachineState.__init__(self, depl, name, id)
        self.service_instance = None

    def _get_service_instance(self):
        if self.service_instance is not None:
            return self.service_instance

        assert self.vsphere_user and self.vsphere_password
        self.service_instance = connect.SmartConnect(host=self.vsphere_host, port=self.vsphere_port,
                                                     user=self.vsphere_user,
                                                     pwd=self.vsphere_password)
        atexit.register(connect.Disconnect, self.service_instance)
        return self.service_instance

    @staticmethod
    def _get_obj_in_list(obj_name, obj_list):
        for o in obj_list:
            if o.name == obj_name:
                return o
        return None

    @staticmethod
    def _get_obj_in_list_or_first(obj_name, obj_list):
        if obj_name is not None:
            return VSphereState._get_obj_in_list(obj_name, obj_list)
        elif len(obj_list) > 0:
            return obj_list[0]
        else:
            return None

    def _get_machine(self):
        service_instance = self._get_service_instance()
        content = service_instance.RetrieveContent()
        machines = content.viewManager.CreateContainerView(content.rootFolder, [vim.VirtualMachine], True).view
        return self._get_obj_in_list(self.vm_id, machines)

    def _get_datacenter(self, dc_name):
        service_instance = self._get_service_instance()
        datacenters = service_instance.content.rootFolder.childEntity
        return self._get_obj_in_list_or_first(dc_name, datacenters)

    def _get_datastore(self, datacenter, ds_name):
        datastores = datacenter.datastoreFolder.childEntity
        return self._get_obj_in_list_or_first(ds_name, datastores)

    def _get_cluster(self, datacenter, cluster_name):
        clusters = datacenter.hostFolder.childEntity
        return self._get_obj_in_list_or_first(cluster_name, clusters)

    def create(self, defn, check, allow_reboot, allow_recreate):
        assert isinstance(defn, VSphereDefinition)

        self.set_common_state(defn)
        self.vsphere_host = defn.config['vsphere']['host']
        self.vsphere_port = defn.config['vsphere']['port']
        self.vsphere_user = defn.config['vsphere']['user']
        self.vsphere_password = defn.config['vsphere']['password']

        if not self.vm_id:
            self.vm_id = "nixops-{0}-{1}".format(self.depl.uuid, self.name)

        if not self.host_public_key:
            (self.host_private_key, self.host_public_key) = nixops.util.create_key_pair()

        if not self.client_public_key:
            (self.client_private_key, self.client_public_key) = nixops.util.create_key_pair()

        if self.state == self.UNKNOWN or check:
            self.check()

        if self.state not in [self.MISSING, self.STOPPED, self.UP]:
            self.logger.warn('machine must be in states MISSING, STOPPED or UP to be created/updated')
            return False

        if self.state == self.MISSING:
            self.logger.log('building VM specification and base image...')

            base_image_size = defn.config['vsphere']['baseImageSize']
            base_image = self._logged_exec(
                ["nix-build", "{0}/vsphere-image.nix".format(self.depl.expr_path),
                 "--arg", "size", '"{0}"'.format(base_image_size)], capture_stdout=True).rstrip()
            base_image += '/disk.vmdk'

            ovf = generate_simple_ovf(self.vm_id, defn.config['vsphere']['vcpu'], defn.config['vsphere']['memorySize'],
                                      base_image_size * 1024, defn.config['vsphere']['networks'])

            datacenter = self._get_datacenter(defn.config['vsphere']['datacenter'])
            assert datacenter is not None
            datastore = self._get_datastore(datacenter, defn.config['vsphere']['datastore'])
            assert datastore is not None
            cluster = self._get_cluster(datacenter, defn.config['vsphere']['cluster'])
            assert cluster is not None

            resource_pool = cluster.resourcePool

            manager = self._get_service_instance().content.ovfManager
            spec_params = vim.OvfManager.CreateImportSpecParams()
            import_spec = manager.CreateImportSpec(ovf, resource_pool, datastore, spec_params)

            self.logger.log('importing virtual machine to vSphere...')
            lease = resource_pool.ImportVApp(import_spec.importSpec, datacenter.vmFolder)

            while lease.state == vim.HttpNfcLease.State.initializing:
                time.sleep(0.1)

            if lease.state != vim.HttpNfcLease.State.ready:
                self.logger.warn('initialization of virtual machine failed')
                return False

            # Transfer VMDK
            disk_url = lease.info.deviceUrl[0].url.replace('*', self.vsphere_host)

            progress = [0]

            def upload_progress(total_size, uploaded_size):
                new_progress = int(float(uploaded_size) / total_size * 100.0)
                if new_progress > progress[0]:
                    lease.HttpNfcLeaseProgress(new_progress)
                    progress[0] = new_progress

            self.logger.log('uploading base image...')
            try:
                with ReadFileMonitor(base_image, 'rb', callback=upload_progress) as f:
                    # FIXME: Why doesn't requests accept the certificate?
                    requests.post(disk_url, data=f, verify=False)
            except (IOError, requests.RequestException) as err:
                self.logger.warn('failed to upload base image ({0})'.format(err))
                lease.HttpNfcLeaseAbort()
                return False

            lease.HttpNfcLeaseComplete()

            if lease.state != vim.HttpNfcLease.State.done:
                self.logger.warn('provisioning of virtual machine failed')
                return False

            machine = self._get_machine()
            assert machine

            guest_config_spec = vim.VirtualMachineConfigSpec()
            guest_config_spec.extraConfig.append(
                vim.option.OptionValue(key='guestinfo.sshPrivateHostKey', value=self.host_private_key))
            guest_config_spec.extraConfig.append(
                vim.option.OptionValue(key='guestinfo.sshPublicHostKey', value=self.host_public_key))
            guest_config_spec.extraConfig.append(
                vim.option.OptionValue(key='guestinfo.sshAuthorizedKeys', value=self.client_public_key))

            self.logger.log('configuring VM...')
            reconfig_task = machine.ReconfigVM_Task(guest_config_spec)
            while reconfig_task.info.state == vim.TaskInfoState.running \
                    or reconfig_task.info.state == vim.TaskInfoState.queued:
                time.sleep(0.1)

            if reconfig_task.info.state == vim.TaskInfoState.error:
                self.logger.warn('failed to configure virtual machine {0}'.format(reconfig_task.info.error))
                machine.Destroy()
                return False

            self.state = self.STOPPED

        if self.state == self.STOPPED:
            self.start()

        return True

    def _update_ip(self):
        machine = self._get_machine()
        assert machine

        new_address = machine.guest.ipAddress
        nixops.known_hosts.update(self.private_ipv4, new_address, self.public_host_key)
        self.ip_address = new_address

    def _wait_for_ip(self):
        self.logger.log_start('waiting for IP address...')
        while True:
            self._update_ip()
            if self.ip_address is not None:
                break
            time.sleep(1)
            self.logger.log_continue('.')
        self.logger.log_end(' ' + self.ip_address)

    def start(self):
        if self.state != self.STOPPED:
            self.logger.warn('machine must be in state STOPPED to be started')
            return

        machine = self._get_machine()
        assert machine

        self.logger.log('starting machine...')
        machine.PowerOn()
        self.state = self.STARTING

        self._wait_for_ip()
        self.wait_for_ssh(check=True)  # wait_for_ssh will update state for us

    def stop(self):
        if self.state != self.UP:
            self.logger.warn('machine must be in state UP to be stopped')
            return

        machine = self._get_machine()
        assert machine

        self.logger.log_start('shutting down...')
        self.state = self.STOPPING

        # FIXME: Maybe use the vSphere API when the open-vm-tools are fixed (they currently try to use /sbin/shutdown)
        self.run_command('systemctl poweroff', check=False)

        while machine.runtime.powerState == vim.VirtualMachinePowerState.poweredOn:
            self.logger.log_continue('.')
            time.sleep(1)

        self.logger.log_end('')
        self.state = self.STOPPED

    def get_ssh_name(self):
        assert self.ip_address
        return self.ip_address

    def get_ssh_private_key_file(self):
        return self._ssh_private_key_file or self.write_ssh_private_key(self.client_private_key)

    def get_ssh_flags(self, *args, **kwargs):
        super_flags = super(VSphereState, self).get_ssh_flags(*args, **kwargs)
        return super_flags + ["-i", self.get_ssh_private_key_file()]

    def destroy(self, wipe=False):
        machine = self._get_machine()

        if machine:
            if not self.depl.logger.confirm("Are you sure you want to destroy VM ‘{0}’?".format(self.name)):
                return False

            if machine.runtime.powerState == vim.VirtualMachinePowerState.poweredOn:
                self.stop()

            machine.Destroy()

        return True

    def _check(self, res):
        machine = self._get_machine()

        res.exists = machine is not None

        if not res.exists:
            self.state = self.MISSING
            self.ip_address = None  # This can no longer be valid
            return

        res.is_up = machine.runtime.powerState == vim.VirtualMachinePowerState.poweredOn

        if not res.is_up:
            self.state = self.STOPPED
            return

        # The machine exists and is up, the default implementation can check the rest
        super(VSphereState, self)._check(res)
