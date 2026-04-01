"""Test class for Hardware Model UI

:Requirement: HardwareModel

:CaseAutomation: Automated

:CaseComponent: Hosts

:Team: Proton

"""

from time import sleep

from fauxfactory import gen_string
import pytest


@pytest.mark.e2e
@pytest.mark.upgrade
def test_positive_end_to_end(session, host_ui_options, module_target_sat):
    """Perform end to end testing for hardware model component

    :id: 93663cc9-7c8f-4f43-8050-444be1313bed

    :expectedresults: All expected CRUD actions finished successfully

    :CaseImportance: Medium

    :BZ:1758260

    """
    name = gen_string('alpha')
    model = gen_string('alphanumeric')
    vendor_class = gen_string('alpha')
    info = gen_string('alpha')
    new_name = gen_string('alpha')
    values, host_name = host_ui_options
    with session:
        session.location.select(values['host.location'])
        # Create new hardware model
        session.hardwaremodel.create(
            {'name': name, 'hardware_model': model, 'vendor_class': vendor_class, 'info': info}
        )
        assert session.hardwaremodel.search(name)[0]['Name'] == name
        hm_values = session.hardwaremodel.read(name)
        assert hm_values['name'] == name
        assert hm_values['hardware_model'] == model
        assert hm_values['vendor_class'] == vendor_class
        assert hm_values['info'] == info
        # Create host with associated hardware model
        session.host.create(values)
        values.update({'additional_information.hardware_model': name})
        session.host.update(host_name, {'additional_information.hardware_model': name})
        host_values = session.host.read(host_name, 'additional_information')
        assert host_values['additional_information']['hardware_model'] == name
        # Update hardware model with new name
        session.hardwaremodel.update(name, {'name': new_name})
        assert session.hardwaremodel.search(new_name)[0]['Name'] == new_name
        host_values = session.host.read(host_name, 'additional_information')
        assert host_values['additional_information']['hardware_model'] == new_name
        # Make an attempt to delete hardware model that associated with host


#       session.hardwaremodel.delete(new_name, err_message=f'{new_name} is used by {host_name}')
#       session.host.update(host_name, {'additional_information.hardware_model': ''})


def test_positive_hardwaremodel_crud(session):
    """Perform CRUD testing for hardware model component

    :id: c8eedf6c-8d57-4c42-8c7f-dcae31e20f48

    :steps:
        1. Create hardware model
        2. Read and verify created hardware model values
        3. Update hardware model name
        4. Verify updated value is searchable and old value is removed
        5. Delete hardware model
        6. Verify hardware model is deleted

    :expectedresults: Hardware model CRUD operations work correctly

    :CaseImportance: Medium
    """
    name = gen_string('alpha')
    model = gen_string('alphanumeric')
    vendor_class = gen_string('alpha')
    info = gen_string('alpha')
    new_name = gen_string('alpha')

    with session:
        # Create hardware model
        session.hardwaremodel.create(
            {
                'name': name,
                'hardware_model': model,
                'vendor_class': vendor_class,
                'info': info,
            }
        )
        sleep(4)  # Wait for the hardware model to be created
        # Verify create
        assert session.hardwaremodel.search(name)[0]['Name'] == name
        sleep(4)  # Wait for the hardware model to be created
        hm_values = session.hardwaremodel.read(name)
        assert hm_values['name'] == name
        assert hm_values['hardware_model'] == model
        assert hm_values['vendor_class'] == vendor_class
        assert hm_values['info'] == info

        # Update name
        session.hardwaremodel.update(name, {'name': new_name})
        sleep(4)  # Wait for the hardware model to be created
        assert session.hardwaremodel.search(new_name)[0]['Name'] == new_name
        assert session.hardwaremodel.search(name)[0]['Hosts'] == 'No Results'

        # Delete
        session.hardwaremodel.delete(new_name)
        sleep(4)  # Wait for the hardware model to be created
        assert session.hardwaremodel.search(new_name)[0]['Hosts'] == 'No Results'
