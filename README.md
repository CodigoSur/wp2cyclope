# wp2cyclope
_WordPress_ to **Cyclope** database migration script.

**wp2cyclope** is part of [Cyclope](http://cyclope.codigosur.org/), a latino django-based CMS by [CódigoSur](http://www.codigosur.org/)

it sits at **cyclope/management/commands/** as a custom [django-admin command](https://docs.djangoproject.com/en/1.4/howto/custom-management-commands/).

working on **python v2.7 django v1.4.2 cyclope 3**

- requires *mysql-connector-python*, install it in your env:
```
$numerico@pc:~$ pip install https://cdn.mysql.com/Downloads/Connector-Python/mysql-connector-python-2.1.5.tar.gz
```

**Usage: manage.py wp2cyclope [options]**

With cyclope's work environment active on a new project,
```
numerico@pc:~$ source ~/cyclope_workenv/bin/activate
$(cyclope_workenv)numerico@pc:~$ cyclopeproject numerica
$(cyclope_workenv)numerico@pc:~$ cd numerica
...
```
run wp2cyclope as a django command
```
$(cyclope_workenv)numerico@pc:~$ python manage.py wp2cyclope --server localhost --database numerica --user nn


        :::::::::::wp2cyclope::::::::::::
        ::WordPress to Cyclope migrator::
        :::::::::::::::::::::::::::::::::

-> hola, amigo!
-> clearing cyclope sqlite database...
-> connecting to wordpress mysql database...
-> nice to meet you, Numérica Latina
-> migrated 8/8 users
-> all users should reset their passwords!
   temporary user passwords default to their username.
-> starting contents migation...
-> migrated 374 articles out of 374 posts
-> migrated 22 static pages out of 22 posts
-> migrated 67 external contents out of 67 links
-> migrated 131 pictures, 12 documents, 5 regular files, 0 sound tracks and 0 movies out of 148 attachments
-> related 122 attachments to their posts or pages as related contents
-> migrated 24 comments
-> migrated 3 collections and 105 categories out of 105 term taxonomies
-> categorized 822 articles, pages, links & attachments

real	1m12.518s
user	0m59.280s
sys	0m2.644s

```

Mandatory:
+ **--server**           WP-Site Host Name.
+ **--user**             Database User.
+ **--database**         Database name.

Optional:
+ **--password**         Database Password.
+ **--table_prefix**     Wordpress DB Table Prefix (defaults to 'wp_').
+ **--default_password** Default password for ALL users. Optional, otherwise usernames will be used.
+ **--devel**            Use http://localhost:8000 instead of site url
