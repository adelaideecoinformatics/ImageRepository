# Deploying to Kubernetes

This assumes
 1. you already have a Kubernetes cluster running
 1. you have `kubectl` installed
 1. `kubectl` is configured to access your cluster

Firstly, let's create a namespace to keep all our related components together
```bash
$ kubectl create namespace imagerepo
```

Next, we need to securely store our OpenStack Swift credentials in a Kubernetes secret (replace all the values with your own)
```bash
$ kubectl create secret generic \
    -n imagerepo \
    image-repo-secrets \
    --from-literal=swiftusername=YOUR_USERNAME_HERE \
    --from-literal=swiftpassword=YOUR_PASSWORD_HERE \
    --from-literal=swifttenantname=YOUR_TENANT_NAME_HERE \
    --from-literal=swifttenantid=YOUR_TENANT_ID_HERE \
    --from-literal=persistentbucket=image-repo \
    --from-literal=cachebucket=image-repo-cache
```

Now we can deploy the stack
```bash
$ kubectl apply -f ImageRepository/kubernetes/image-repository.yml
```

Check the progress of the deploy with
```bash
$ kubectl get -n imagerepo pod
NAME                                       READY     STATUS              RESTARTS   AGE
image-repository-server-2226121017-4q9q5   0/1       ContainerCreating   0          41s
```

Once `STATUS=Running`, we can find what port the service is bound to. Look at the `PORT(S)` column for the `image-repo-service`, it should show a port number above 30,000
```bash
$ kubectl get -n imagerepo service
NAME                 TYPE        CLUSTER-IP       EXTERNAL-IP   PORT(S)          AGE
image-repo-service   NodePort    10.106.53.254    <none>        80:31819/TCP     10m
```

In this case, it's `31819`. You can now access a listing of images at http://your-cluster-ip:31819/images (no trailing slash).

Optionally, you can also create an Ingress by creating a YAML descriptor like
```yaml
# imagerepo-ingress.yml
apiVersion: extensions/v1beta1
kind: Ingress
metadata:
  name: image-repository-ingress
  namespace: imagerepo
spec:
  rules:
  - host: imagerepo.example.com # update with your domain name, don't forget to create the DNS entry
    http:
      paths:
      - backend:
          serviceName: image-repo-service
          servicePort: 80
```
...then deploy it with
```bash
$ kubectl apply -f imagerepo-ingress.yml
ingress "image-repository-ingress" created
$ kubectl get -n imagerepo ing # check that it worked
NAME                       HOSTS                                  ADDRESS   PORTS     AGE
image-repository-ingress   imagerepo.example.com                            80        1m
```
You should now be able to list images on your ImageRepostory at http://imagerepo.example.com/images (no trailing slash).

Congratulations on deploying your ImageRepository.
