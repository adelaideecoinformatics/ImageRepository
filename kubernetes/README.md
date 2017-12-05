# Deploying to Kubernetes

This assumes you have the following:
 1. a Kubernetes cluster running
 1. `kubectl` installed
 1. `kubectl` is configured to access your cluster
 1. API keys for an OpenStack instance
 1. two buckets created in OpenStack Swift to store images in (you'll update the config to point to these shortly)

Firstly, let's create a namespace to keep all our related components together
```bash
$ kubectl create namespace paratoo
```

Next, we need to securely store our OpenStack Swift credentials in a Kubernetes secret. Either replace all the values with your own or ensure that the env variables are defined. Make sure the Swift buckets exist in Swift or change the names to ones that do.
```bash
$ kubectl create secret generic \
    -n paratoo \
    paratoo-secrets \
    --from-literal=swiftusername=$OS_USERNAME \
    --from-literal=swiftpassword=$OS_PASSWORD \
    --from-literal=swifttenantname=$OS_TENANT_NAME \
    --from-literal=swifttenantid=$OS_TENANT_ID \
    --from-literal=persistentbucket=image-repo \
    --from-literal=cachebucket=image-repo-cache
```

Now we can deploy the stack
```bash
$ kubectl apply -n paratoo -f paratoo-image-repo/kubernetes/paratoo.yml
# or if you don't want to clone the repo to your machine
$ kubectl apply -n paratoo -f https://raw.githubusercontent.com/adelaideecoinformatics/paratoo-image-repo/master/kubernetes/paratoo.yml
```

Check the progress of the deploy with
```bash
$ kubectl get -n paratoo pod
NAME                                       READY     STATUS              RESTARTS   AGE
paratoo-server-2226121017-4q9q5            0/1       ContainerCreating   0          41s
```

Once `STATUS=Running`, we can find what port the service is bound to. Look at the `PORT(S)` column for the `paratoo-service`, it should show a port number above 30,000
```bash
$ kubectl get -n paratoo service
NAME                 TYPE        CLUSTER-IP       EXTERNAL-IP   PORT(S)          AGE
paratoo-service      NodePort    10.106.53.254    <none>        80:31819/TCP     10m
```

In this case, it's `31819`. You can now access a listing of images at http://your-cluster-ip:31819/images (no trailing slash).

Optionally, you can also create an Ingress by creating a YAML descriptor like
```yaml
# paratoo-ingress.yml
apiVersion: extensions/v1beta1
kind: Ingress
metadata:
  name: paratoo-ingress
  namespace: paratoo
spec:
  rules:
  - host: paratoo.example.com # update with your domain name, don't forget to create the DNS entry
    http:
      paths:
      - backend:
          serviceName: paratoo-service
          servicePort: 80
```
...then deploy it with
```bash
$ kubectl apply -f paratoo-ingress.yml
ingress "paratoo-ingress" created
$ kubectl get -n paratoo ing # check that it worked
NAME                       HOSTS                                  ADDRESS   PORTS     AGE
paratoo-ingress   paratoo.example.com                              80        1m
```
You should now be able to list images on your paratoo-image-repo at http://paratoo.example.com/images (no trailing slash).

Congratulations on deploying your paratoo-image-repo.
