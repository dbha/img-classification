#!/bin/bash

if [ "${TYPE}" = "S3" ]; then
  echo "Starting Batch Job"
  /config/k8s-infer --model ${MODELS} --type S3 --endpoint ${ENDPOINT} --access_key ${ACCESS_KEY} --secret_key ${SECRET_KEY} --images_bucket ${IMAGE_BUCKET} --classes_bucket ${CLASSES_BUCKET}  --workload ${WORKLOAD}
fi
