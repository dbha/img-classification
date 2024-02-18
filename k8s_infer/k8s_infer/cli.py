
import argparse
import click
import os, sys, subprocess
import boto3

from torchvision.io import read_image
from torchvision.models.quantization import resnet50, ResNet50_QuantizedWeights
from torchvision.models.alexnet import alexnet, AlexNet_Weights
from torchvision.models.googlenet import googlenet, GoogLeNet_Weights

import torchvision.models as models
import torch
from PIL import Image
from torchvision import transforms
from efficientnet_pytorch import EfficientNet

from minio import Minio
from minio.error import S3Error


# 모델명 vaildation 확인
def check_pretrained_model(input_model_name):

    # 허용가능한 models 추출
    all_model_names = [name for name in dir(models) if callable(getattr(models, name))]

    # non-model 필터링 
    all_model_names = [name for name in all_model_names if not name.startswith("__")]

    # 모델명 포힘여부 확인
    for model_name in all_model_names:
        if model_name.lower() == input_model_name.lower():
        #   print(f"{input_model_name} is right model")
            check_result = True
            break
        else:
        #   print(f"{input_model_name} is wrong model")
          check_result = False
        
    return check_result

# 이미지 file type 체크
def check_file_type(input_image_name):

    # 파일위치, 파일명 분리
    directory, file_name = os.path.split(input_image_name)
    root, extension = os.path.splitext(file_name)

    if extension in ['.PNG','.JPEG','.png','.jpeg']:
        # print('this image is correct type')
        return True
    else:
        return False

# K8s 에 배포
def deploy_kubernetes(yaml, dict, type):
    try:
        print("Start to deploy workload on Kubernetes")
        subprocess.run(["kubectl", "apply", "-f", yaml], check=True)
        print("Deployment successful!")
    except subprocess.CalledProcessError as e:
        print(f"Error deploying YAML file: {e}")
        sys.exit(0)

# Object Storage 로부터 이미지 다운로드
def download_image_from_minio(endpoint, access_key, secret_key, bucket, bucket_type, yaml, type, workload):

    # S3 로부터 이미지를 다운받은 위치는 크게 2가지
    # yaml 파일이 있으면 Container 안에서 호출하는 것으로 다운로드 위치는 /tmp/container/s3 
    # yaml이 공백이면 Laptop 에서 호출되는 것으로 다운로드 위치는 /tmp/local/s3 

    try:
        # MinIO 서버에 연결
        minio_client = Minio(endpoint, access_key, secret_key, secure=False)

        # # MinIO 버킷에서 이미지 다운로드(한건)
        # minio_client.fget_object(bucket, object_name, local_folder)

        # MinIO 버킷 내의 모든 객체 목록 가져오기
        objects = minio_client.list_objects(bucket, recursive=True)

        # if type is not None and type.strip() == "Local":
        # Container 로 이미지를 다운로드 하는 경우
        if workload.strip() == "C":
            if bucket_type == 'images':
                # local_folder = "/config/download-s3-images"
                local_folder = "/tmp/container/s3/download-s3-images"
            else:
                # local_folder = "/config/imagenet-classes"
                local_folder = "/tmp/container/s3/imagenet-classes"  
        else:
            # Laptop 으로 이미지를 다운로드 하는 경우
            if bucket_type == 'images':
                local_folder = "/tmp/local/s3/download-s3-images"
                # local_folder = "/Users/dbha/Workspaces/rebellions/download-s3-images"
            else:
                local_folder = "/tmp/local/s3/imagenet-classes"
                # local_folder = "/Users/dbha/Workspaces/rebellions/imagenet-classes"             

        os.makedirs(local_folder, exist_ok=True)
        delete_files_in_directory(local_folder)

        # 각 객체를 다운로드하여 로컬에 저장
        for obj in objects:
            object_name = obj.object_name 
            local_path = os.path.join(local_folder, object_name)

            # MinIO 버킷에서 이미지 다운로드
            minio_client.fget_object(bucket, object_name, local_path)

            print(f"Downloaded: {object_name} -> {local_path}")
    except S3Error as err:
        print(err)
        sys.exit(1)

# Object Storage 로부터 다운로드후 inference 수행
def inference_s3_image(input_model_name, input_image_name, endpoint, access_key, secret_key, images_bucket, classes_bucket, yaml, s3_dict, type, workload):

    # kubectl 을 통해 Pod 배포 S3 통해 다운로드
    if (yaml.strip() != "" and workload.strip() == ""):
        try:
            deploy_kubernetes(yaml, s3_dict, type)
            sys.exit(0)
        except Exception as e:
            print(f"An unexpected error occurred: {e}")

    # 배포된 컨테이너에서 S3 통해 다운로드    
    if (yaml.strip() == "" and workload.strip() == "C"):
        try:    
            # 컨테이너에서 다운로드
            download_image_from_minio(endpoint, access_key, secret_key, classes_bucket, 'classes', yaml, type, workload)
            download_image_from_minio(endpoint, access_key, secret_key, images_bucket, 'images', yaml, type, workload)
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
    else:
        # Laptop에서 다운로드
        download_image_from_minio(endpoint, access_key, secret_key, classes_bucket, 'classes', yaml, type, workload)
        download_image_from_minio(endpoint, access_key, secret_key, images_bucket, 'images', yaml, type, workload)

    model_class = getattr(models, input_model_name, None)

    print("\n\nmodel_class : ", model_class)
    model = model_class(pretrained=True)
    model.eval()

    preprocess = transforms.Compose([
        transforms.Resize(256),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])

    # ImageNet 데이터셋의 클래스를 컨테이너 안에서 가져오기
    if workload.strip() == "C":
        imagenet_classes_name='/tmp/container/s3/imagenet-classes'
    else:        
        imagenet_classes_name='/tmp/local/s3/imagenet-classes'   

    classes_file_list = os.listdir(imagenet_classes_name)

    for file_name in classes_file_list:
        file_path = os.path.join(imagenet_classes_name, file_name)
        print(file_path)

    # 컨테이너 안에서 classification을 위한 image 가져오기
    if workload.strip() == "C":
        download_images_path_name='/tmp/container/s3/download-s3-images'
    else:
        download_images_path_name='/tmp/local/s3/download-s3-images'
    
    images_file_list = os.listdir(download_images_path_name)

    # image에 대해 개별건으로 inference 수행
    for image_file_name in images_file_list:
        image_file_path = os.path.join(download_images_path_name, image_file_name)
        print("image_file_path", image_file_path)

        img = Image.open(image_file_path)
        input_tensor = preprocess(img)

        print("input_tensor:\n", input_tensor)
        input_batch = input_tensor.unsqueeze(0)

        # prediction = model(batch).squeeze(0).softmax(0)
        prediction = model(input_batch).squeeze(0).softmax(0)

        # ImageNet 데이터셋의 클래스 목록 가져오기
        imagenet_classes_path = file_path
        with open(imagenet_classes_path) as f:
            classes = [line.strip() for line in f.readlines()]

        # # 예측된 클래스 ID 가져오기
        class_id = prediction.argmax().item()
        score = prediction[class_id].item()

        # print("class_id : ", class_id)

        # # 클래스 레이블 출력
        predicted_class_label = classes[class_id]
        # print(f"predicted_class_label: {predicted_class_label}")
    
        # print("weight class_id:", class_id)
        # category_name = weights.meta["categories"][class_id]
        print(f"class id: {predicted_class_label}: {100 * score}%\n")


# Local에 저장된 이미지를 추론하는 함수
# Local은 사용자 laptop 이거나 Container 일 수 있으며, 이는 yaml 파일을 통해 확인
# 이미지 위치는 Container 의 경우 /tmp/s3 라는 디렉토리를 사용하며, 사용자 laptop일 경우 /tmp/local 디렉토리 사용
# Local환경에서의 Container 사용의미는 k8s-infer --yaml 을 Pod를 통해 Local 이미지를 읽어서 추론한다는 의미 
def inference_local_image(input_model_name, input_image_name, yaml, local_dict, type):
        
    # 두가지 형태가 있으며 input 파라미터를 통해 이미지를 직접 입력한 경우와 Local laptop 의 특정위치(/tmp/local/existing)에 저장된
    # 이미지를 읽어들이는 방식이 있음

    model_class = getattr(models, input_model_name, None)
    print("\n\nmodel_class : ", model_class)

    model = model_class(pretrained=True)   # 입력받은 모델을 생성, pretrained 매개변수를 통해서 사전 훈련된 가중치를 사용하여 초기화 한다.

    model.eval()  # 모델을 추론 모드로 전환

    # preprocess = weights.transforms()

    # 이미지를 전처리하기 위한 여러 변환 함수들이 순서대로 적용된 변환 파이프라인 생성
    preprocess = transforms.Compose([
        transforms.Resize(256),  # 이미지 크기 조절
        transforms.CenterCrop(224),
        transforms.ToTensor(),  # 이미지를 텐서로 변환
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]), # 정규화
    ])

    # 입력받은 이미지 한건에 대한 추론
    if input_image_name.strip() != "":

        try:
            img = Image.open(input_image_name)

            input_tensor = preprocess(img)

            print("input_tensor: ", input_tensor)
            input_batch = input_tensor.unsqueeze(0)

            # prediction = model(batch).squeeze(0).softmax(0)
            prediction = model(input_batch).squeeze(0).softmax(0)   # softmax를 통해 해당 차원의 값들을 확률 값으로 변환
        
            # ImageNet 데이터셋의 클래스 목록 가져오기
            imagenet_classes_path = "/tmp/local/existing/imagenet-classes/imagenet_classes.txt"  # 클래스 목록 파일을 로컬에 다운로드
            with open(imagenet_classes_path) as f:
                classes = [line.strip() for line in f.readlines()]

            # # 예측된 클래스 ID 가져오기 
            class_id = prediction.argmax().item()  # 가장 높은 확률을 가진 클래스 선택
            score = prediction[class_id].item()

            # print("class_id : ", class_id)

            # # 클래스 레이블 출력
            predicted_class_label = classes[class_id]
            # print(f"predicted_class_label: {predicted_class_label}")
        
            # print("weight class_id:", class_id)
            # category_name = weights.meta["categories"][class_id]
            print(f"class id: {predicted_class_label}: {100 * score}%")

        except Exception as e:    
            print(f"\nAn unexpected error occurred: {e}")

    # 컨테이너에서 로컬 디렉토리를 읽어서 처리 /tmp/local/existing       
    else:
        # Container 를 통해 추론 시작
        if yaml.strip() != "":
            try:
                deploy_kubernetes(yaml, s3_dict, type)
            except Exception as e:
                print(f"An unexpected error occurred: {e}")

# 입력값 None에 대한 공백처리
def process_args(args):
    for key, value in vars(args).items():
        # value가 None이면 공백으로 초기화
        setattr(args, key, '' if value is None else value)

def delete_files_in_directory(directory):
    # 디렉토리 안의 모든 파일 목록 가져오기
    file_list = os.listdir(directory)

    # 디렉토리 안의 각 파일에 대해 삭제 수행
    for filename in file_list:
        file_path = os.path.join(directory, filename)
        try:
            if os.path.isfile(file_path):
                # 파일인 경우 삭제
                os.remove(file_path)
            elif os.path.isdir(file_path):
                # 디렉토리인 경우 재귀적으로 호출하여 디렉토리 안의 파일 삭제
                delete_files_in_directory(file_path)
        except Exception as e:
            print(f"Error deleting {file_path}: {e}")


def main():

    parser = argparse.ArgumentParser(
        # description="An over-simplified downloader to demonstrate python packaging."
        description="k8s-infer CLI to demonstrate ml inference leveraging torchvision model"
    )
    parser.add_argument(
        "--models", metavar='model1,model2,model3', type=str,
        help="Input pre-trained Models by Comma-separated values"
    )
    parser.add_argument(
        "--image", type=str,
        help="Input Image Path"
    )
    parser.add_argument(
        "--type", type=str,
        help="Input Local or S3"
    )

    # S3 Option일 경우, 파라미터 체크
    parser.add_argument(
        "--endpoint", type=str,
        help="Input s3 end_point"
    )
    parser.add_argument(
        "--access_key", type=str,
        help="Input S3 Access key"
    )
    parser.add_argument(
        "--secret_key", type=str,
        help="Input S3 Secret Key"
    )
    parser.add_argument(
        "--images_bucket", type=str,
        help="Input Bucket name where the image is saved"
    )
    parser.add_argument(
        "--classes_bucket", type=str,
        help="Input Bucket name where the classes files is saved"
    ) 
    parser.add_argument(
        "--yaml", type=str,
        help="Enter the yaml path where you want to deploy Kubernetes. \
              In this case, Only the --yaml file path and --type(S3 or Local) option must be used for deployment."
    )
    parser.add_argument(
        "--workload", type=str,
        help="How to get images to make inferences, In this case, default is ' '.", default=""
    ) 
    
    args = parser.parse_args()

    # 값이 None인 경우 공백으로 초기화
    process_args(args)

    # input_model_name = args.models
    
    input_image_name = args.image
    type             = args.type
    endpoint         = args.endpoint
    access_key       = args.access_key
    secret_key       = args.secret_key
    images_bucket    = args.images_bucket
    classes_bucket   = args.classes_bucket
    yaml             = args.yaml
    workload         = args.workload
    
    if args.models:
        # 쉼표로 구분된 값을 리스트로 분리
        model_list = args.models.split(',')
    else:
        if yaml.strip() == "":
            print("Please Input input_model_name\n")
            sys.exit(0)

    try:
        # Non K8s 실행 (Local)
        if yaml.strip() == "":

            # 입력된 Model 에 대한 확인
            for model_str in model_list:
                # 쉼표로 구분된 값을 리스트로 분리
                values = model_str.split(',')

                for input_model_name in values:
                    # models 및 type 입력 확인
                    # if input_model_name is None or input_model_name.strip() == "":
                    #     print("Please Input input_model_name\n")
                    #     sys.exit(0)
                    check_model=check_pretrained_model(input_model_name)

                    if check_model:
                        # print("valid model : ", input_model_name)
                        print(f"valid model : {input_model_name}")
                    else:
                        # print("invaild model : ", input_model_name)
                        print(f"invaild model : {input_model_name}")
                        sys.exit(0)                

            if type.strip() != "Local" and type.strip() != "S3":
                print("\nPlease Input type only S3 or Local\n")
                sys.exit(0)

            print("type: ", type)

            # k8s-cli로 Local 디렉토리에 있는 이미지 추론
            # Local에 추론해야 할 대상 이미지가 사전에 저장되어 있어야 함
            if type.strip() == "Local":
                # print("\nCall inference_local_image")

                if input_image_name.strip() == "":
                    print("\nPlease Input image path\n")
                    sys.exit(0)

                check_image=check_file_type(input_image_name)
                if check_image:
                    # print("valid image_type : ", input_image_name")
                    print(f"valid image_type : {input_image_name}\n")
                else:
                    # print("invaild image_type : ", input_image_name)
                    print(f"\ninvaild image_type : {input_image_name}\n")
                    sys.exit(0)
                
                local_dict = {"models_key": input_model_name, "input_image_name_key": input_image_name}

                for model_str in model_list:
                    values = model_str.split(',')
                    for input_model_name in values:
                        inference_local_image(input_model_name, input_image_name, yaml, local_dict, type)

            elif type.strip() == "S3":

                if yaml.strip() == "":
                    # print("Call inference_s3_image\n")

                    if endpoint is None or endpoint.strip() == "":
                        print("\nplease Input endpoint and access_key and secret_key and images_bucket and images_bucket")
                        sys.exit(0)
                    if access_key is None or access_key.strip() == "":
                        print("\nplease Input endpoint and access_key and secret_key and images_bucket and images_bucket")
                        sys.exit(0)                                                                                                       
                    if secret_key is None or secret_key.strip() == "":
                        print("\nplease Input endpoint and access_key and secret_key and images_bucket and images_bucket")
                        sys.exit(0)
                    if images_bucket is None or images_bucket.strip() == "":
                        print("\nplease Input endpoint and access_key and secret_key and images_bucket and images_bucket")
                        sys.exit(0)
                    if classes_bucket is None or classes_bucket.strip() == "":
                        print("\nplease Input endpoint and access_key and secret_key and images_bucket and images_bucket")
                        sys.exit(0)


                    for model_str in model_list:
                        values = model_str.split(',')
                        print(values)

                        for input_model_name in values:
                            s3_dict = {"models_key": input_model_name, "endpoint_key": endpoint, "access_key": access_key, "secret_key": secret_key, "images_bucket_key": images_bucket, "classes_bucket_key": classes_bucket}
                            inference_s3_image(input_model_name, input_image_name, endpoint, access_key, secret_key, images_bucket, classes_bucket, yaml, s3_dict, type, workload)

                else:
                    print(f"invaild type : {type}")
                    sys.exit(0)  
            else:
                print(f"invaild type : {type}")
                sys.exit(0)      

        # K8s 실행 (Container)        
        else:
            # Use Local Path
            # Container 안에서 Image를 다운로드 하지 않고 Laptop 이미지를 읽어서 추론
            # print("Deploy on Kubernetes")
            # print("type is", type)
            # 우선은 kubernets 배포는 S3만 허용!

            if args.models or endpoint.strip() !='' or access_key.strip() !='' or secret_key.strip() !='' or images_bucket !='':
                print("To use kubernetes, Only Input parameter --type --yaml")
                sys.exit(0)

            # 허용하지 않음(only S3만) -> PV hostpath 및 PVC를 활용해야 함
            if type.strip() == "Local":
                print("In the current version, type only allows S3.")
                sys.exit(0)

                # local_dict = {"models_key": input_model_name, "input_image_name_key": input_image_name}
                # inference_local_image(input_model_name, input_image_name, yaml, local_dict, type)

            # Container 안에서 Image를 다운로드 후 다운로드 된 이미지를 읽어서 추론
            elif type.strip() == "S3": 
                input_model_name=""  # 공백으로 초기화 yaml안에 모델이 들어가 있음
                s3_dict = {"models_key": "", "endpoint_key": "", "access_key": "", "secret_key": "", "images_bucket_key": "", "classes_bucket_key": ""}
                inference_s3_image(input_model_name, input_image_name, endpoint, access_key, secret_key, images_bucket, classes_bucket, yaml, s3_dict, type, workload)
            else:
                print("Please Check Input type(S3 or Local) Option\n")
                sys.exit(0)

    except Exception as e:    
        print(f"\nAn unexpected error occurred: {e}") 

if __name__ == "__main__":
    main()
    # inference_image()