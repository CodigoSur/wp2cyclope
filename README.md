# wp2cyclope
WordPress to [Cyclope](http://cyclope.codigosur.org/) database migration script.

**Usage: manage.py wp2cyclope [options]**

With cyclope's work environment active on a new project,
```
numerico@pc:~$ source ~/cyclope_workenv/bin/activate
$(cyclope_workenv)numerico@pc:~$ cyclopeproject numerica
$(cyclope_workenv)numerico@pc:~$ cd numerica
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
   default temporary password for all users: alohawaii.
-> migrated 374 articles out of 374 posts
-> migrated 22 static pages out of 22 posts
-> migrated 23 comments

real	1m12.518s
user	0m59.280s
sys	0m2.644s

```

Mandatory:
+ **--server=SERVER**       WP-Site Host Name.
+ **--user=USER**           Database User.
+ **--password=PASSWORD**   Database Password.
+ **--database=DB**         Database name.

Optional:
+ **--table_prefix=WP_PREFIX**

                        Wordpress DB Table Prefix (defaults to 'wp_').
+ **--default_password=WP_USER_PASSWORD**

                        Default password for ALL users. Optional, otherwise username will be used.s
