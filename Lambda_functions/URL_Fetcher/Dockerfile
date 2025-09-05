# Lambda base image with Python 3.11
FROM public.ecr.aws/lambda/python:3.11

# Install Python deps
RUN pip install --no-cache-dir boto3 ddgs

# Copy function code
COPY app.py ${LAMBDA_TASK_ROOT}

# Set the Lambda handler
CMD ["app.lambda_handler"]
