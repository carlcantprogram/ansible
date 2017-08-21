#!/usr/bin/python

# (c) 2017, NetApp, Inc
# (c) 2017, Carl Nielsen
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type


ANSIBLE_METADATA = {'metadata_version': '1.0',
                    'status': ['preview'],
                    'supported_by': 'community'}


DOCUMENTATION = '''

module: na_cdot_clone

short_description: Creat NetApp cDOT clones
extends_documentation_fragment:
    - netapp.ontap
version_added: '2.3-Carl'
author: Carl Nielsen

description:
- Create or destroy felxclones on NetApp cDOT

options:

  state:
    description:
    - Whether the specified clone should exist or not.
    required: true
    choices: ['present', 'absent']

  name:
    description:
    - The name of the felxclone to manage.
    required: true

  online:
    description:
    - Whether the specified clone is online, or not.
    choices: ['True', 'False']
    default: 'True'

  parent_vol:
    description:
    - The name of the volume to clone from
    required: true

  snapshot_name:
    description:
    - Optional snapshot to clone from

  vserver:
    description:
    - Name of the vserver to use.
    required: true
    default: None

'''

EXAMPLES = """

    - name: Create FlexClone
      na_cdot_clone:
        state: present
        name: ansibleVolume
        online: true
        parent_vol: cloneMeVol
        snapshot_name: mySnapshot
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


class NetAppCDOTClone(object):

    def __init__(self):

        self.argument_spec = netapp_utils.ontap_sf_host_argument_spec()
        self.argument_spec.update(dict(
            state=dict(required=True, choices=['present', 'absent']),
            name=dict(required=True, type='str'),
            is_online=dict(required=False, type='bool', default=True, aliases=['online']),
            parent_vol=dict(type='str', aliases=['parent_volume']),
            snapshot_name=dict(required=False, type='str'),
            vserver=dict(required=True, type='str', default=None),
        ))

        self.module = AnsibleModule(
            argument_spec=self.argument_spec,
            required_if=[
                ('state', 'present', ['parent_vol'])
            ],
            supports_check_mode=True
        )

        p = self.module.params

        # set up state variables
        self.state = p['state']
        self.name = p['name']
        self.is_online = p['is_online']
        self.parent_vol = p['parent_vol']
        self.snapshot_name = p['snapshot_name']
        self.vserver = p['vserver']

        if HAS_NETAPP_LIB is False:
            self.module.fail_json(msg="the python NetApp-Lib module is required")
        else:
            self.server = netapp_utils.setup_ontap_zapi(module=self.module, vserver=self.vserver)

    def get_clone(self):
        """
        Return details about the clone
        :param:
            name : Name of the cone

        :return: Details about the clone. None if not found.
        :rtype: dict
        """
        volume_info = netapp_utils.zapi.NaElement('volume-get-iter')
        volume_attributes = netapp_utils.zapi.NaElement('volume-attributes')
        volume_id_attributes = netapp_utils.zapi.NaElement('volume-id-attributes')
        volume_id_attributes.add_new_child('name', self.name)
        volume_attributes.add_child_elem(volume_id_attributes)

        query = netapp_utils.zapi.NaElement('query')
        query.add_child_elem(volume_attributes)

        volume_info.add_child_elem(query)

        result = self.server.invoke_successfully(volume_info, False)

        return_value = None

        if result.get_child_by_name('num-records') and \
                int(result.get_child_content('num-records')) >= 1:

            volume_attributes = result.get_child_by_name(
                'attributes-list').get_child_by_name(
                'volume-attributes')
            # Get volume's current size
            volume_space_attributes = volume_attributes.get_child_by_name(
                'volume-space-attributes')
            current_size = volume_space_attributes.get_child_content('size')

            # Get volume's state (online/offline)
            volume_state_attributes = volume_attributes.get_child_by_name(
                'volume-state-attributes')
            current_state = volume_state_attributes.get_child_content('state')
            is_online = None
            if current_state == "online":
                is_online = True
            elif current_state == "offline":
                is_online = False
            return_value = {
                'name': self.name,
                'size': current_size,
                'is_online': is_online,
            }

        return return_value

    def create_clone(self):
        clone_in = netapp_utils.zapi.NaElement.create_node_with_children(
            'volume-clone-create', **{'volume': self.name,
                                'parent-volume': self.parent_vol})

        if (self.snapshot_name):
            clone_in.add_new_child("parent-snapshot", self.snapshot_name)

        try:
            self.server.invoke_successfully(clone_in,
                                            enable_tunneling=False)
        except netapp_utils.zapi.NaApiError as e:
            self.module.fail_json(msg='Error cloning volume %s to %s: %s' %
                                  (self.parent_vol, self.name, to_native(e)),
                                  exception=traceback.format_exc())

    def change_volume_state(self):
        """
        Change volume's state (offline/online).
        """
        state_requested = None
        if self.is_online:
            # Requested state is 'online'.
            state_requested = "online"
            volume_change_state = netapp_utils.zapi.NaElement.create_node_with_children(
                'volume-online',
                **{'name': self.name})
        else:
            # Requested state is 'offline'.
            state_requested = "offline"
            volume_change_state = netapp_utils.zapi.NaElement.create_node_with_children(
                'volume-offline',
                **{'name': self.name})
        try:
            self.server.invoke_successfully(volume_change_state,
                                            enable_tunneling=True)
        except netapp_utils.zapi.NaApiError as e:
            self.module.fail_json(msg='Error changing the state of volume %s to %s: %s' %
                                  (self.name, state_requested, to_native(e)),
                                  exception=traceback.format_exc())

    def delete_volume(self):
        print("delete_volume not implemented")

    def apply(self):
        changed = False
        clone_exists = False
        clone_detail = self.get_clone()

        if clone_detail:
            clone_exists = True

            if self.state == 'absent':
                changed = True

            elif self.state == 'present':
                if (clone_detail['is_online'] is not None) and (clone_detail['is_online'] != self.is_online):
                    changed = True

        else:
            if self.state == 'present':
                changed = True

        if changed:
            if self.module.check_mode:
                pass
            else:
                if self.state == 'present':
                    if not clone_exists:
                        self.create_clone()

                    else:
                        if clone_detail['is_online'] is not \
                                None and clone_detail['is_online'] != \
                                self.is_online:
                            self.change_volume_state()

                elif self.state == 'absent':
                    self.delete_volume()

        self.module.exit_json(changed=changed)


def main():
    v = NetAppCDOTClone()
    v.apply()

if __name__ == '__main__':
    main()
