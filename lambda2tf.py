import json
import os
import textwrap
import boto3

TERRAFORM_FOLDER_PATH = "terraform/lambda"

# Change the following vars to the folders containing the zip files for Lambda Layers and Lambda Functions
LAMBDA_LAYERS_ZIP_FOLDER = "terraform/files/lambda_layers"
LAMBDA_FUNCTIONS_ZIP_FOLDER = "terraform/files/lambda_functions"


def return_all_func_names(session):
    all_func_names = []
    lambda_client = session.client('lambda')
    all_func_objects = lambda_client.list_functions()

    for f in all_func_objects['Functions']:
        all_func_names.append(f['FunctionName'])

    while "NextMarker" in all_func_objects:
        next_marker = all_func_objects['NextMarker']
        all_func_objects = lambda_client.list_functions(Marker=next_marker)

        for f in all_func_objects['Functions']:
            all_func_names.append(f['FunctionName'])

    return all_func_names


def layers2tf(session):
    lambda_client = session.client('lambda')
    layer_definitions = ""
    layers_file = f"{TERRAFORM_FOLDER_PATH}/lambda_layers.tf"

    print('Creating Terraform Configuration for Lambda Layers')

    for path in [TERRAFORM_FOLDER_PATH, LAMBDA_LAYERS_ZIP_FOLDER]:
        if not os.path.exists(path):
            os.makedirs(path)

    for layer in lambda_client.list_layers()['Layers']:
        layer_name = layer['LayerName']
        compatible_runtimes = json.dumps(layer['LatestMatchingVersion']['CompatibleRuntimes'])
        description = layer['LatestMatchingVersion'].get('Description', "")
        zip_path = f"{LAMBDA_LAYERS_ZIP_FOLDER}/{layer_name}.zip"

        layer_definitions += f"""
        resource "aws_lambda_layer_version" "{layer_name}" {{
            filename              = "{zip_path}"
            layer_name            = "{layer_name}"
            compatible_runtimes   = {compatible_runtimes}
            description           = "{description}"
            source_code_hash      = filebase64sha256("{zip_path}")
            }}
        """
    with open(layers_file, 'w') as f:
        f.write(textwrap.dedent(layer_definitions))


def aliases2tf(session):
    if not os.path.exists(TERRAFORM_FOLDER_PATH):
        os.makedirs(TERRAFORM_FOLDER_PATH)

    print('Creating Terraform Configuration for Lambda Aliases')

    lambda_client = session.client('lambda')
    aliases_file = f"{TERRAFORM_FOLDER_PATH}/lambda_aliases.tf"

    aliases_tf_definitions_body = ""

    for func_name in return_all_func_names(session):
        aliases = lambda_client.list_aliases(FunctionName=func_name).get('Aliases', [])
        for alias in aliases:
            name = alias.get('Name')
            func_version = alias.get('FunctionVersion')
            description = alias.get('Description', '')

            aliases_tf_definitions_body = f"""
                resource "aws_lambda_alias" "{func_name}-{name}" {{
                    name = "{name}"
                    description = "{description}"
                    function_name = aws_lambda_function.{func_name}.arn
                    function_version = "{func_version}"
                }}
            """
    with open(aliases_file, 'w') as f:
        f.write(textwrap.dedent(aliases_tf_definitions_body))


def functions2tf(session):
    for path in [TERRAFORM_FOLDER_PATH, LAMBDA_FUNCTIONS_ZIP_FOLDER]:
        if not os.path.exists(path):
            os.makedirs(path)

    print('Creating Terraform Configuration for Lambda Functions & Lambda Concurrency Configs')

    lambda_functions_definitions_tf_file = f"{TERRAFORM_FOLDER_PATH}/lambda_functions.tf"
    lambda_functions_concurrency_definitions_tf_file = f"{TERRAFORM_FOLDER_PATH}/lambda_concurrency.tf"

    lambda_client = session.client('lambda')

    lambda_functions_tf_body = ""
    lambda_concurrency_tf_body = ""

    for func_name in return_all_func_names(session):
        func = lambda_client.get_function(FunctionName=func_name)
        lambda_config = func['Configuration']
        lambda_tags = func.get('Tags', {})
        lambda_env_vars = func.get('Environment', {}).get('Variables', {})
        tf_tags = ""
        tf_env = ""

        if lambda_tags:
            tf_tags = f'tags = {json.dumps(lambda_tags).replace(":", " = ")}'

        if lambda_env_vars:
            tf_env = f"""
              environment {{
                variables = {json.dumps(lambda_env_vars).replace(":", " = ")}  
              }}"""

        lambda_functions_tf_body += f"""
            resource "aws_lambda_function" "{func_name}" {{
              filename          = "{LAMBDA_FUNCTIONS_ZIP_FOLDER}/{func_name}.zip"
              function_name     = "{lambda_config.get('FunctionName')}"
              role              = "{lambda_config.get('Role', "")}"
              handler           = "{lambda_config.get('Handler')}"
              description       = "{lambda_config.get('Description')}"
              publish           = "true"
              timeout           = {lambda_config.get('Timeout')}
              memory_size       = {lambda_config.get('MemorySize')}
              runtime           = "{lambda_config.get('Runtime')}"
              layers            = {json.dumps(list(map(lambda x: "aws_lambda_layer.{}.arn".
                                                       format(x['Arn'].split(':')[x['Arn'].split(':').index('layer') + 1]),
                                                       lambda_config.get('Layers', [])))).replace('"', '')}
              source_code_hash  = filebase64sha256("{LAMBDA_FUNCTIONS_ZIP_FOLDER}/{func_name}.zip")

              tracing_config {{
                mode = "{lambda_config.get('TracingConfig', {}).get('Mode', 'PassThrough')}"
              }}

              vpc_config {{
                    subnet_ids         =  {json.dumps(lambda_config.get('VpcConfig', {}).get('SubnetIds', []))}
                    security_group_ids =  {json.dumps(lambda_config.get('VpcConfig', {}).get('SecurityGroupIds', []))}
              }}

              {tf_tags}
              {tf_env}

            }}"""

        con_configs = lambda_client.list_provisioned_concurrency_configs(FunctionName=func_name).get(
            'ProvisionedConcurrencyConfigs', [])

        for con_config in con_configs:
            lambda_concurrency_tf_body += f"""
                resource "aws_lambda_provisioned_concurrency_config" "{func_name}-concurrency" {{
                    function_name = {func_name}
                    provisioned_concurrent_executions = {con_config.get('RequestedProvisionedConcurrentExecutions')}
                    qualifier = {con_config['FunctionArn'].split(':')[-1]}
                    depends_on = [aws_lambda_function.{func_name}]
                }}"""

        with open(lambda_functions_definitions_tf_file, 'w') as f:
            f.write(textwrap.dedent(lambda_functions_tf_body))

        with open(lambda_functions_concurrency_definitions_tf_file, 'w') as f:
            f.write(textwrap.dedent(lambda_concurrency_tf_body))
