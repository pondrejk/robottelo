from datetime import datetime

from fauxfactory import gen_string
import pytest


@pytest.fixture(scope='module')
def module_generate_report(module_target_sat):
    filename = f'usage_report-{datetime.timestamp(datetime.now())}-{gen_string("alphanumeric")}.yml'
    result = module_target_sat.execute(f'satellite-maintain report generate --output {filename}')
    assert result.status == 0, 'failed to generate report'
    return module_target_sat.load_remote_yaml_file(filename)
