##############################################################################
# BlastRadius demo scenario 3 - "public sensitive S3 bucket"
#
# Never applied to a real AWS account; this is analysis input only.
#
# Baseline: the whole stack is private. The sensitive bucket is reachable only
# through the application role, and the instance is not internet-facing.
#
# before/ and after/ differ only in the bucket ACL.
##############################################################################

provider "aws" {
  region = "us-east-1"
}

resource "aws_security_group" "app" {
  name        = "app-sg"
  description = "Internal application traffic only"

  ingress {
    description = "HTTPS from the internal load balancer subnet"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/24"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "reporting" {
  ami           = "ami-0c55b159cbfafe1f0"
  instance_type = "t3.micro"

  vpc_security_group_ids = [aws_security_group.app.id]
  iam_instance_profile   = aws_iam_instance_profile.reporting.name

  tags = {
    Name = "reporting-worker"
  }
}

resource "aws_iam_role" "reporting" {
  name = "reporting-role"

  assume_role_policy = <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "ec2.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
POLICY
}

resource "aws_iam_instance_profile" "reporting" {
  name = "reporting-instance-profile"
  role = aws_iam_role.reporting.name
}

resource "aws_iam_role_policy" "reporting_read" {
  name = "reporting-read"
  role = aws_iam_role.reporting.id

  policy = <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": ["${aws_s3_bucket.customer_data.arn}/*"]
    }
  ]
}
POLICY
}

resource "aws_s3_bucket" "customer_data" {
  bucket = "acme-customer-data"

  tags = {
    Name      = "customer-data"
    Sensitive = "true"
    DataClass = "pii"
  }
}

# A static-site refactor is about to flip this ACL. BlastRadius should notice
# that this particular bucket is not a static site.
resource "aws_s3_bucket_acl" "customer_data" {
  bucket = aws_s3_bucket.customer_data.id
  acl    = "public-read"
}
