from django.core.management.base import BaseCommand, CommandError
from optparse import make_option
import mysql.connector
from cyclope.models import SiteSettings
import re
from cyclope.apps.articles.models import Article
from django.contrib.sites.models import Site
from django.db import transaction
from cyclope.apps.staticpages.models import StaticPage
from django.contrib.contenttypes.models import ContentType
from cyclope.apps.custom_comments.models import CustomComment

class Command(BaseCommand) :
    help = """Migrates a site in WordPress to Cyclope CMS.
    Requires the options server, database and user, passphrase is optional.
    Optional WordPress table prefix option, defaults to 'wp_'."""

    #NOTE django > 1.8 uses argparse instead of optparse module, 
    #so "You are encouraged to exclusively use **options for new commands."
    #https://docs.djangoproject.com/en/1.9/howto/custom-management-commands/
    option_list = BaseCommand.option_list + (
        make_option('--server',
            action='store',
            dest='server',
            default=None,
            help='WP-Site Host Name.'
        ),
        make_option('--user',
            action='store',
            dest='user',
            default=None,
            help='Database User.'
        ),
        make_option('--password',
            action='store',
            dest='password',
            default=None,
            help='Database Password.'
        ),
        make_option('--database',
            action='store',
            dest='db',
            default=None,
            help='Database name.'
        ),
        make_option('--table_prefix',
            action='store',
            dest='wp_prefix',
            default='wp_',
            help='Wordpress DB Table Prefix (defaults to \'wp_\').'
        ),
    )

    # class constant
    wp_prefix = 'wp_'

    def handle(self, *args, **options):
        """WordPress to Cyclope DataBase Migration Logic."""
        print"""
        :::::::::::wp2cyclope::::::::::::
        ::WordPress to Cyclope migrator::
        :::::::::::::::::::::::::::::::::\n\n-> hola, amigo!"""

        self.wp_prefix = options['wp_prefix']
        
        print "-> clearing cyclope sqlite database..."
        self._clear_cyclope_db()
        
        print "-> connecting to wordpress mysql database..."
        cnx = self._mysql_connection(options['server'], options['db'], options['user'], options['password'])
        
        # SiteSettings <- wp_options
        settings = self._fetch_site_settings(cnx)
        print "-> nice to meet you, "+settings.site.name
        
        # Articles <- wp_posts
        wp_posts_a_count, articles_count = self._fetch_articles(cnx)
        print "-> migrated {} articles out of {} posts".format(articles_count, wp_posts_a_count)

        # StaticPages <- wp_posts
        wp_posts_p_count, pages_count = self._fetch_pages(cnx)
        print "-> migrated {} static pages out of {} posts".format(pages_count, wp_posts_p_count)    

        # Comments <- wp_comments
        self._fetch_comments(cnx, settings.site)

        #...
        #close mysql connection
        cnx.close()
        # WELCOME
    ####

    def _mysql_connection(self, host, database, user, password):
        """Establish a MySQL connection to the given option params and return it."""
        config = {
            'host': host,
            'database': database,
            'user': user
        }
        if not password is None : config['password']=password
        try:
            cnx = mysql.connector.connect(**config)
            return cnx
        except mysql.connector.Error as err:
            if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
                print "Wrong User name or Password."
            elif err.errno == errorcode.ER_BAD_DB_ERROR:
                print "Database doesn't exist."
            else:
                print err
            raise
        else:
            return cnx

    def _clear_cyclope_db(self):
        #TODO clearing settings erases default layout & breaks
        #SiteSettings.objects.all().delete()
        #Site.objects.all().delete()
        Article.objects.all().delete()
        StaticPage.objects.all().delete()

    def _fetch_site_settings(self, mysql_cnx):
        """Execute single query to WP _options table to retrieve the given option names."""
        options = ('siteurl', 'blogname', 'blogdescription', 'home', 'default_comment_status', 'comment_moderation', 'comments_notify')
        #TODO comment_registration, users_can_register, blog_public
        #single query
        query = "SELECT option_name, option_value FROM "+self.wp_prefix+"options WHERE option_name IN {}".format(options)
        cursor = mysql_cnx.cursor()
        cursor.execute(query)
        wp_options = dict(cursor.fetchall())
        cursor.close()
        #see _clear_cyclope_db TODO
        #settings = SiteSettings()
        settings = SiteSettings.objects.all()[0]
        #site = Site()
        site = settings.site
        #
        settings.global_title = wp_options['blogname']
        settings.description = wp_options['blogdescription']
        #NOTE settings.keywords = WP doesn't use meta tags, only as a plugin
        settings.allow_comments = u'YES' if wp_options['default_comment_status']=='open' else u'NO'
        settings.moderate_comments = wp_options['comment_moderation']==1 #default False
        settings.enable_comments_notifications = wp_options['comments_notify'] in ('', 1) #default True
        site.name = wp_options['blogname']
        site.domain = wp_options['siteurl']#TODO strip http:// 
        site.save()
        settings.site = site
        settings.save()
        return settings

    def _fetch_articles(self, mysql_cnx):
        """Queries the given fields to WP posts table selecting only posts, not pages nor attachments nor revisions,
           It parses data as key-value pairs to instance rows as Articles and save them.
           Returns the number of created Articles and of fetched rows in a tuple."""
        fields = ('ID', 'post_title', 'post_status', 'post_date', 'post_modified', 'comment_status', 'post_content', 'post_excerpt')
        query = re.sub("[()']", '', "SELECT {} FROM ".format(fields))+self.wp_prefix+"posts WHERE post_type='post'"
        cursor = mysql_cnx.cursor()
        cursor.execute(query)
        #single transaction for all articles
        transaction.enter_transaction_management()
        transaction.managed(True)
        for wp_post in cursor :
            article = self._post_to_article(dict(zip(fields, wp_post)))
            article.save() 
        transaction.commit()
        transaction.leave_transaction_management()
        counts = (cursor.rowcount, Article.objects.count())
        cursor.close()
        return counts 

    def _fetch_pages(self, mysql_cnx):
        """Queries to WP posts table selecting only pages, not posts nor attachments nor revisions."""
        fields = ('ID', 'post_title','post_status','post_date', 'post_modified',  'comment_status', 'post_content', 'post_excerpt')
        query = re.sub("[()']", '', "SELECT {} FROM ".format(fields))+self.wp_prefix+"posts WHERE post_type='page'"
        cursor = mysql_cnx.cursor()
        cursor.execute(query)
        #single transaction for all pages
        transaction.enter_transaction_management()
        transaction.managed(True)
        for wp_post in cursor :
            page = self._post_to_static_page(dict(zip(fields, wp_post)))
            page.save()
        transaction.commit()
        transaction.leave_transaction_management()
        counts = (cursor.rowcount, StaticPage.objects.count())
        cursor.close()
        return counts 

    def _fetch_comments(self, mysql_cnx, site):
        """Populates cyclope custom comments from WP table wp_comments.
           Instead of querying the related object for each comment and atomizing transactions, which could be expensive,
           We use an additional query for each content type only (just 2) and the transaction is repeated just as many times.
           So we receive content_type and posts IDs, as well as Site ID which is already above in the script."""
        fields = ('comment_author', 'comment_author_email', 'comment_author_url', 'comment_content', 'comment_date', 'comment_author_IP', 'comment_approved', 'comment_parent', 'user_id', 'comment_post_ID')
        post_types_with_comments = ('post', 'page')#TODO attachments
        for post_type in post_types_with_comments:
            post_ids = self._post_type_ids(mysql_cnx, post_type)
            content_type_id = self._post_content_type_id(post_type)
            query = re.sub("[()']", '', "SELECT {} FROM ".format(fields))+self.wp_prefix+"comments WHERE comment_approved!='spam' AND comment_post_ID IN {}".format(post_ids)
            cursor = mysql_cnx.cursor()
            cursor.execute(query)
            #single transaction per content_type
            transaction.enter_transaction_management()
            transaction.managed(True)
            for wp_comment in cursor:
                comment_hash = dict(zip(fields,wp_comment))
                comment = self._wp_comment_to_custom(comment_hash, site, content_type_id)
                comment.save()
            transaction.commit()
            transaction.leave_transaction_management()
            cursor.close()

    def _post_type_ids(self, mysql_cnx, post_type):
        """Returns the IDs of wp_posts of the given type.
           Type can be 'post', 'page' or 'attachment'."""
        query = "SELECT ID FROM "+self.wp_prefix+"posts WHERE post_type='{}';".format(post_type)
        cursor = mysql_cnx.cursor()
        cursor.execute(query)
        post_ids = cursor.fetchall()
        cursor.close()
        def _flat_result(row): return row[0]
        post_ids = tuple(map(_flat_result, post_ids))
        return post_ids

    def _post_content_type_id(self, post_type):
        if post_type == 'post':
            return ContentType.objects.get(app_label="articles", model="article")
        elif post_type == 'page':
            return ContentType.objects.get(app_label="staticpages", model="staticpage")
        #TODO elif post_type == 'attachment'
        else:
            raise "Unexistent post type!"
        
    #TODO 15+ Failed to populate slug Article.slug from name
    #TODO PRESERVE PERMALINKS
    def _post_to_article(self, post):
        """Instances an Article object from a WP post hash."""
        return Article(
            id = post['ID'],
            name = post['post_title'],
            #post_name is AutoSlug 
            text = post['post_content'],
            date = post['post_date'], #redundant
            creation_date = post['post_date'],
            modification_date = post['post_modified'],
            published = post['post_status']=='publish',#private and draft are unpublished
            #TODO all posts have a status, they are saved as the option that's set(?).
            #if the user then tries to close them all, he shouldn't set them one by one.
            #whe should set them to SITE default unless comments are explicitly closed, which is the minority(?)       
            allow_comments = post['comment_status']=='open',
            summary = post['post_excerpt']
            #pretitle has no equivalent in WP
            #TODO show_author=always user #FKs: user comments related_contents picture author source
        )

    def _post_to_static_page(self, post):
        return StaticPage(
            id = post['ID'],
            name = post['post_title'],
            text = post['post_content'],
            creation_date = post['post_date'],
            modification_date = post['post_modified'],
            published = post['post_status']=='publish',#private and draft are unpublished
            allow_comments = post['comment_status']=='open',#TODO see article's allow_comments
            summary = post['post_excerpt']
            #TODO user related_contents comments show_author
        )

    def _wp_comment_to_custom(self, comment, site, content_type):
        return CustomComment(
            object_pk = comment['comment_post_ID'],
            content_type = content_type,
            #together they make content_object
            site = site,
            #user               user_id #FK/None TODO
            user_name = comment['comment_author'],
            user_email = comment['comment_author_email'],
            user_url = comment['comment_author_url'],
            comment = comment['comment_content'],
            submit_date = comment['comment_date'],
            ip_address = comment['comment_author_IP'],
            #TODO
            #is_public          comment_approved
            #is_removed         ..
            #TODO THREADED
            #title              x
            #parent             comment_parent
            #last_child         
            #tree_path          
            #CUSTOM
            subscribe = True #TODO Site default?
        )
