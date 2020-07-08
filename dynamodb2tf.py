import json
import os
import textwrap
import boto3

os.environ["TZ"] = "UTC"
TERRAFORM_FILE_PATH = "terraform/dynamodb/"


class TerraformDict(dict):
    def __str__(self):
        return json.dumps(self)


class TerraformList(list):
    def __str__(self):
        return json.dumps(self)


def return_hash_and_range_keys(key_schema):
    hash_key = range_key = ""
    for attr in key_schema:
        if attr['KeyType'] == 'HASH':
            hash_key = attr['AttributeName']
        else:
            range_key = attr['AttributeName']
    return {'hash_key': hash_key, 'range_key': range_key}


def dynamo_tables_to_tf(s=boto3.Session()):
    print("Creating Terraform Configuration for Dynamodb Tables")

    dynamodb_tables_tf_file_path = f"{TERRAFORM_FILE_PATH}/dynamodb_tables.tf"
    dynamodb_tables_definitions_body = ""

    if not os.path.exists(TERRAFORM_FILE_PATH):
        os.makedirs(TERRAFORM_FILE_PATH)

    client = s.client('dynamodb')
    all_table_names = client.list_tables()["TableNames"]

    for name in all_table_names:
        table = client.describe_table(TableName=name)['Table']

        table_keys_dict = return_hash_and_range_keys(table.get('KeySchema'))
        table_hash_key = table_keys_dict['hash_key']
        table_range_key = table_keys_dict['range_key']

        attribute_definitions = []
        for attr in table.get('AttributeDefinitions'):
            attribute_definitions.append(TerraformDict(attr))

        try:
            billing_mode = table['BillingModeSummary'].get('BillingMode', 'PAY_PER_REQUEST')
        except KeyError:
            billing_mode = 'PAY_PER_REQUEST'

        provisioned_throughput = table.get('ProvisionedThroughput')
        pitr = client.describe_continuous_backups(TableName=name).get('ContinuousBackupsDescription').get(
            'PointInTimeRecoveryDescription').get('PointInTimeRecoveryStatus')
        if pitr == 'DISABLED':
            pitr = "false"
        else:
            pitr = "true"

        lsis = table.get('LocalSecondaryIndexes', [])
        final_lsis = []

        for lsi in lsis:
            lsi_keys_dict = return_hash_and_range_keys(lsi.get('KeySchema'))
            lsi_range_key = lsi_keys_dict['range_key']
            transformed_lsi = {
                'IndexName': lsi['IndexName'],
                'Projection': lsi.get('Projection'),
                'range_key': lsi_range_key,
            }
            final_lsis.append(transformed_lsi)

        gsis = table.get('GlobalSecondaryIndexes', [])
        final_gsis = []

        for gsi in gsis:
            gsi_keys_dict = return_hash_and_range_keys(gsi.get('KeySchema'))
            gsi_hash_key = gsi_keys_dict['hash_key']
            gsi_range_key = gsi_keys_dict['range_key']
            gsi_provisioned_throughput = gsi.get('ProvisionedThroughput')
            del gsi_provisioned_throughput['NumberOfDecreasesToday']
            transformed_gsi = {
                'IndexName': gsi['IndexName'],
                'hash_key': gsi_hash_key,
                'range_key': gsi_range_key,
                'Projection': gsi.get('Projection'),
                'ProvisionedThroughput': gsi_provisioned_throughput
            }
            final_gsis.append(transformed_gsi)
        stream_specification = table.get('StreamSpecification')
        if stream_specification:
            stream_spec = f"""
              stream_enabled = "true"
              stream_view_type = "{stream_specification['StreamViewType']}" """
        else:
            stream_spec = 'stream_enabled = "false"'

        attributes = ""
        gsis = ""
        lsis = ""
        for attr in table.get('AttributeDefinitions'):
            attributes += f"""
                attribute {{
                  name = "{attr["AttributeName"]}"
                  type = "{attr["AttributeType"]}"
                }} """

        for gsi in final_gsis:
            gsis += f"""
                global_secondary_index {{
                  name = "{gsi["IndexName"]}"
                  hash_key = "{gsi["hash_key"]}"
                  range_key = "{gsi["range_key"]}"
                  write_capacity = "{gsi["ProvisionedThroughput"].get('WriteCapacityUnits')}"
                  read_capacity = "{gsi["ProvisionedThroughput"].get("ReadCapacityUnits")}"
                  projection_type = "{gsi["Projection"].get("ProjectionType")}"
                  non_key_attributes = {gsi["Projection"].get("NonKeyAttributes", [])}
                }} """

        for lsi in final_lsis:
            lsis += f"""
                local_secondary_index {{
                  name = "{lsi["IndexName"]}"
                  range_key = "{lsi["range_key"]}"
                  projection_type = "{lsi["Projection"].get("ProjectionType")}"
                  non_key_attributes = {lsi["Projection"].get("NonKeyAttributes", [])}              
                }} """

        dynamodb_tables_definitions_body += f"""    
            resource aws_dynamodb_table "{name}" {{
                name = "{name}"
                billing_mode = "{billing_mode}"
                read_capacity = "{provisioned_throughput['ReadCapacityUnits']}"
                write_capacity = "{provisioned_throughput['WriteCapacityUnits']}"  
                hash_key = "{table_hash_key}"
                range_key = "{table_range_key}"
                {stream_spec}
                {attributes}
                {lsis}
                {gsis}
                point_in_time_recovery {{
                    enabled = {pitr}
                }}           
            }} """

    with open(dynamodb_tables_tf_file_path, 'w') as f:
        f.write(textwrap.dedent(dynamodb_tables_definitions_body))
