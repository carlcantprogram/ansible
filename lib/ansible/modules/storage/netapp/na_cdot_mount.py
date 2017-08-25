#!/usr/bin/python

# (c) 2017, NetApp, Inc
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type


ANSIBLE_METADATA = {'metadata_version': '1.0',
                    'status': ['preview'],
                    'supported_by': 'community'}


DOCUMENTATION = '''

module: na_cdot_mount

short_description: Manage NetApp cDOT mounts
extends_documentation_fragment:
    - netapp.ontap
version_added: '2.3'
author: Carl Nielsen

description:
- mount netapp volumes on cDOT

options:

  state:
    description:
    - Whether the specified volume should be mounted or not.
    required: true
    choices: ['mounted', 'unmounted']

  name:
    description:
    - The name of the volume to manage.
    required: true

  policy_name:
    description:
    - The name of the export policy to use when mounting the volume.
    required: false
    default: default

  junction_path:
    description:
    - Junction path for mounting volume
    required: false
    default: use volume name

  vserver:
    description:
    - Name of the vserver to use.
    required: true
    default: None

'''

EXAMPLES = """

    - name: Mount Volume
      na_cdot_mount
        state: mounted
        name: ansibleVolume
        policy_name: ansibleExport
        vserver: ansibleVServer
        hostname: "{{ netapp_hostname }}"
        username: "{{ netapp_username }}"
        password: "{{ netapp_password }}"

    - name: Unmount Volume
      na_cdot_volume:
        state: unmounted
        name: ansibleVolume
        policy_name: ansibleExport
        vserver: ansibleVServer
        hostname: "{{ netapp_hostname }}"
        username: "{{ netapp_username }}"
        password: "{{ netapp_password }}"

"""

RETURN = """


"""
import traceback

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils._text import to_native
import ansible.module_utils.netapp as netapp_utils


HAS_NETAPP_LIB = netapp_utils.has_netapp_lib()


class NetAppCDOTMount(object):

    def __init__(self):

        self.argument_spec = netapp_utils.ontap_sf_host_argument_spec()
        self.argument_spec.update(dict(
            state=dict(required=True, choices=['mounted', 'unmounted']),
            name=dict(required=True, type='str'),
            junction_path=dict(required=False, type='str'),
            policy_name=dict(required=False, type='str'),
            vserver=dict(required=True, type='str', default=None),
        ))

        self.module = AnsibleModule(
            argument_spec=self.argument_spec,
            supports_check_mode=True
        )

        p = self.module.params

        # set up state variables
        self.state = p['state']
        self.name = p['name']
        self.vserver = p['vserver']

        if p['state'] == 'mounted':
            if p['junction_path'] is None:
                self.junction_path = '/' + self.name
            else:
                self.junction_path = p['junction_path']

        if HAS_NETAPP_LIB is False:
            self.module.fail_json(msg="the python NetApp-Lib module is required")
        else:
            self.server = netapp_utils.setup_ontap_zapi(module=self.module, vserver=self.vserver)

    def get_volume(self):
        """
        Return junction path and status
        :param:
            name : Name of the volume

        :return: Details about the volume. None if not found.
        :rtype: dict
        """
        #Mount point - volume-attributes -> volume-id-attributes -> junction-path
        #Mount status - volume-attributes -> volume-state-attributes -> is-junction-active
        volume_info = netapp_utils.zapi.NaElement('volume-get-iter')
        volume_attributes = netapp_utils.zapi.NaElement('volume-attributes')
        volume_id_attributes = netapp_utils.zapi.NaElement('volume-id-attributes')
        volume_id_attributes.add_new_child('name', self.name)
        volume_attributes.add_child_elem(volume_id_attributes)

        query = netapp_utils.zapi.NaElement('query')
        query.add_child_elem(volume_attributes)

        volume_info.add_child_elem(query)

        result = self.server.invoke_successfully(volume_info, True)

        return_value = None

        if result.get_child_by_name('num-records') and \
                int(result.get_child_content('num-records')) >= 1:

            volume_attributes = result.get_child_by_name(
                'attributes-list').get_child_by_name(
                'volume-attributes')
            # Get volume's state (online/offline)
            volume_state_attributes = volume_attributes.get_child_by_name(
                'volume-state-attributes')
            volume_id_attributes = volume_attributes.get_child_by_name(
                'volume-id-attributes')
            current_state = volume_state_attributes.get_child_content('state')
            junction_active = volume_state_attributes.get_child_content('is-junction-active')
            junction_path = volume_id_attributes.get_child_content('junction-path')
            is_online = None
            if current_state == "online":
                is_online = True
            elif current_state == "offline":
                is_online = False
            return_value = {
                'name': self.name,
                'junction_active': junction_active,
                'junction_path': junction_path,
            }

        return return_value

    def mount_volume(self):
        volume_mount = netapp_utils.zapi.NaElement.create_node_with_children(
                               'volume-mount', **{'volume-name': self.name,
                               'junction-path': self.junction_path})

        try:
            self.server.invoke_successfully(volume_mount,
                                            enable_tunneling=True)
        except netapp_utils.zapi.NaApiError as e:
            self.module.fail_json(msg='Error mounting volume %s: %s' % (self.name, to_native(e)),
                                  exception=traceback.format_exc())

    def unmount_volume(self):
        volume_unmount = netapp_utils.zapi.NaElement.create_node_with_children(
                               'volume-unmount', **{'volume-name': self.name,
                               'force': 'true'})

        try:
            self.server.invoke_successfully(volume_unmount,
                                            enable_tunneling=True)
        except netapp_utils.zapi.NaApiError as e:
            self.module.fail_json(msg='Error unmounting volume %s: %s' % (self.name, to_native(e)),
                                  exception=traceback.format_exc())


#    def change_policy(self):
#        """
#        Change the export policy.
#
#        """
#        try:
#            self.server.invoke_successfully(volume_rename,
#                                            enable_tunneling=True)
#        except netapp_utils.zapi.NaApiError as e:
#            self.module.fail_json(msg='Error renaming volume %s: %s' % (self.name, to_native(e)),
#                                  exception=traceback.format_exc())

    def apply(self):
        # Can't rename a junction, need to unmount / mount
        # 1. If unmount requested, unmount - the end
        # 2. If junction changed unmount / mount - the end
        # 3. If state is inactive, make active - the end
        changed = False
        rename = False
        unmount = False
        mount = False
        volume_detail = self.get_volume()

        if volume_detail:
            # IF volume mounted
            if volume_detail['junction_path'] is not None:
                if self.state == 'unmounted':
                    changed = True
                    unmount = True
                else:
                    # Junction path changed
                    if volume_detail['junction_path'] != self.junction_path:
                        changed = True
                        rename = True
                    # Junction inactive
                    elif volume_detail['junction_active'] == False:
                        changed = True
                        mount = True
            # Mount requested
            elif self.state == 'mounted':
                changed = True
                mount = True

        if changed:
            if self.module.check_mode:
                pass
            else:
                if unmount:
                    self.unmount_volume()
                elif mount:
                    self.mount_volume()
                elif rename:
                    self.unmount_volume()
                    self.mount_volume()

        self.module.exit_json(changed=changed)


def main():
    v = NetAppCDOTMount()
    v.apply()

if __name__ == '__main__':
    main()
