# -*- coding: utf-8 -*-

import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom
import StringIO

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


class VSphereState(MachineState):
    client_public_key = nixops.util.attr_property("vsphere.clientPublicKey", None)
    client_private_key = nixops.util.attr_property("vsphere.clientPrivateKey", None)

    @classmethod
    def get_type(cls):
        return "vsphere"

    def create(self, defn, check, allow_reboot, allow_recreate):
        assert isinstance(defn, VSphereDefinition)

    def destroy(self, wipe=False):
        return True
