from airflow import DAG
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from airflow.operators.dagrun_operator import TriggerDagRunOperator
from airflow.operators.bash_operator import BashOperator
from airflow.operators.dummy_operator import DummyOperator
from datetime import datetime, timedelta

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 22),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    # 'retry_delay': timedelta(minutes=30),
}

dag = DAG(
    'deploy_inference_dag',
    default_args=default_args,
    description='A simple DAG Test to deploy alexnet and resnet50 with KubernetesPodOperator',
    schedule_interval=timedelta(days=1),
)

# Define parameters For alexnet
workload_alexnet_value = "C"
type_alexnet_value = "S3"
models_alexnet_value = "alexnet"
endpoint_alexnet_value = "minio-svc.minio-dev:9000"
access_key_alexnet_value = "${ACCESS_KEY}"
secret_key_alexnet_value = "${SECRET_KEY}"
image_bucket_alexnet_value = "batch-images"
classes_bucket_alexnet_value = "imagenet-classes"

start = DummyOperator(task_id='start', dag=dag)

inference_alexnet_task = KubernetesPodOperator(
    task_id='deploy_alexnet',
    name='inference-alexnet-container',
    namespace='airflow',  # Specify the Kubernetes namespace
    image='dbha/k8s-infer-cli-image:3',
    env_vars={
            "WORKLOAD": workload_alexnet_value,
            "TYPE": type_alexnet_value,
            "MODELS": models_alexnet_value,
            "ENDPOINT": endpoint_alexnet_value,
            "ACCESS_KEY": access_key_alexnet_value,
            "SECRET_KEY": secret_key_alexnet_value,
            "IMAGE_BUCKET": image_bucket_alexnet_value,
            "CLASSES_BUCKET": classes_bucket_alexnet_value,                                   
        },
    cmds=['/bin/bash', '-c'],
    arguments=["/config/start.sh"],
    get_logs=True,
    dag=dag,
)

# Define parameters For alexnet
workload_resnet_value = "C"
type_resnet_value = "S3"
models_resnet_value = "resnet50"
endpoint_resnet_value = "minio-svc.minio-dev:9000"
access_key_resnet_value = "dbha0719"
secret_key_resnet_value = "password"
image_bucket_resnet_value = "images"
classes_bucket_resnet_value = "imagenet-classes"

inference_resnet50_task = KubernetesPodOperator(
    task_id='deploy_resnet50',
    name='inference-resnet50-container',
    namespace='airflow',  # Specify the Kubernetes namespace
    image='dbha/k8s-infer-cli-image:3',
    env_vars={
            "WORKLOAD": workload_resnet_value,
            "TYPE": type_resnet_value,
            "MODELS": models_resnet_value,
            "ENDPOINT": endpoint_resnet_value,
            "ACCESS_KEY": access_key_resnet_value,
            "SECRET_KEY": secret_key_resnet_value,
            "IMAGE_BUCKET": image_bucket_resnet_value,
            "CLASSES_BUCKET": classes_bucket_resnet_value,                                   
        },
    cmds=['/bin/bash', '-c'],
    arguments=["/config/start.sh"],
    get_logs=True,
    dag=dag,
)

# # Execute dag_alexnet and then, trigger  dag_resnet50
# trigger_b = TriggerDagRunOperator(
#     task_id='trigger_dag_resnet50',
#     trigger_dag_id='dag_resnet50',
#     dag=dag_alexnet,
# )

end = DummyOperator(task_id='end', dag=dag)

inference_alexnet_task.set_upstream(start)
inference_alexnet_task.set_downstream(end)

# inference_resnet50_task.set_upstream(start)
# inference_resnet50_task.set_downstream(end)

# deploy_alexnet_task >> trigger_b

# deploy_container_task.set_upstream(start)
