FROM tiangolo/uwsgi-nginx-flask:python2.7
COPY ./setup.py /
COPY ./src /app
RUN ln -s /app /src
WORKDIR /
RUN python /setup.py install
COPY ./docker/config.yml /config.yml
COPY ./docker/swift.sh /swift.sh
COPY ./docker/entrywrapper.sh /entrywrapper.sh
COPY ./docker/uwsgi.ini /app/uwsgi.ini
ENV CACHE_DIR=/tmp/image_server
RUN mkdir $CACHE_DIR
RUN chmod 600 $CACHE_DIR
# mount a host dir that has the expected dirs
# get logs written to a file
# production-ise log rotation
WORKDIR /app
ENTRYPOINT [ "/entrywrapper.sh" ]
CMD ["/usr/bin/supervisord"]
