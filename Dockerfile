FROM tiangolo/uwsgi-nginx-flask:python2.7
COPY ./setup.py /
COPY ./src /app
RUN ln -s /app /src
WORKDIR /
RUN python /setup.py install
COPY ./docker/config.yml /config.yml
COPY ./docker/entrywrapper.sh /entrywrapper.sh
COPY ./docker/uwsgi.ini /app/uwsgi.ini
ENV CACHE_DIR=/tmp/image_server
RUN mkdir $CACHE_DIR
RUN chmod 600 $CACHE_DIR
WORKDIR /app
ENTRYPOINT [ "/entrywrapper.sh" ]
CMD ["/usr/bin/supervisord"]
