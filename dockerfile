FROM 00jlich/abs-kosync-bridge:latest

# Install Flask
RUN pip install flask

# Keep the default CMD from base image