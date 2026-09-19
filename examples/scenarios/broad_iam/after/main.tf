##############################################################################
# BlastRadius demo scenario 2 - "overly broad IAM permission"
#
# Never applied to a real AWS account; this is analysis input only.
#
# Baseline: the web server is INTENTIONALLY public on 443 (it is a web server).
# Its role can only read the non-sensitive logs bucket, so the internet-facing
# instance is not a path to sensitive data.
#
# before/ and after/ differ only in the IAM policy statement.
##############################################################################

provider "aws" {
  region = "us-east-1"
}

resource "aws_security_group" "web" {
  name        = "web-sg"
  description = "Public HTTPS listener"

  ingress {
    description = "HTTPS from anywhere - this is a public website"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "web_server" {
  ami           = "ami-0c55b159cbfafe1f0"
  instance_type = "t3.micro"

  vpc_security_group_ids = [aws_security_group.web.id]
  iam_instance_profile   = aws_iam_instance_profile.app.name

  tags = {
    Name = "web-server"
  }
}

resource "aws_iam_role" "app" {
  name = "app-role"

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

resource "aws_iam_instance_profile" "app" {
  name = "app-instance-profile"
  role = aws_iam_role.app.name
}

resource "aws_iam_role_policy" "app_logs" {
  name = "app-logs-write"
  role = aws_iam_role.app.id

  policy = <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:*"],
      "Resource": ["*"]
    }
  ]
}
POLICY
}

resource "aws_s3_bucket" "app_logs" {
  bucket = "acme-app-logs"

  tags = {
    Name = "app-logs"
  }
}

resource "aws_s3_bucket" "customer_data" {
  bucket = "acme-customer-data"

  tags = {
    Name      = "customer-data"
    Sensitive = "true"
    DataClass = "pii"
  }
}
