# aws2tf
This repo contains functions to create terraform templates from existing AWS resources. The functions use the AWS python
library, boto3, to connect to AWS and read the resources configuration. Next it writes down a terraform configuration 
file containing the resources declarations. Of course the resources must be imported to the state file after this step 
before managing them with terraform. Import scripts will be provided wherever possible.

## Requirements

In order to use these functions you must have appropriate read access to the resources you are creating the terraform 
configuration for. 

## Current AWS Resources Support

Currently there are functions for the following  AWS Resources: 
 - Dynamodb Tables, Event Mappings for Stream Enabled Tables
 - Lambda Functions, Layers, Aliases & Provisioned Concurrency Configs 
 
Many more will be added progressively. 