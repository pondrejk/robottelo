'''Test class for MCP server

:CaseAutomation: Automated

:CaseComponent: API

:Team: Endeavour

:Requirement: API

:CaseImportance: High

'''

from fastmcp import Client
import pytest


@pytest.mark.asyncio
async def test_positive_mcp_client(module_mcp_target_sat):
    '''

    :id: 6f3c31c2-2f50-43ba-ac52-b3ebc6af4e45

    :expectedresults: MCP server is running
    '''
    async with Client(
        'http://ip-10-0-168-108.rhos-01.prod.psi.rdu2.redhat.com:8080/mcp/'
    ) as client:
        result = await client.ping()
        __import__('pdb').set_trace()
        result = await client.call_tool(
            'call_foreman_api', {'resource': 'hosts', 'action': 'index', 'params': {}}
        )
        assert result.data['message'] == "Action 'index' on resource 'hosts' executed successfully."
        # assert result.data['response']['total'] == 3 #number of returned hosts
        # list of hosts
        # result.data['response']['results']
        # list of hostnames
        # [host['name'] for host in result.data['response']['results']]
