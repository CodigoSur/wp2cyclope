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
from django.contrib.auth.models import User
from cyclope.core.collections.models import Collection, Category, Categorization

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
        make_option('--default_password',
            action='store',
            dest='wp_user_password',
            default=None,
            help='Default password for ALL users. Optional, otherwise username will be used.s'
        ),
    )

    # class constant
    wp_prefix = 'wp_'
    wp_user_password = None

    def handle(self, *args, **options):
        """WordPress to Cyclope DataBase Migration Logic."""
        print"""
        :::::::::::wp2cyclope::::::::::::
        ::WordPress to Cyclope migrator::
        :::::::::::::::::::::::::::::::::\n\n-> hola, amigo!"""

        self.wp_prefix = options['wp_prefix']
        self.wp_user_password = options['wp_user_password']
        
        print "-> clearing cyclope sqlite database..."
        self._clear_cyclope_db()
        
        print "-> connecting to wordpress mysql database..."
        cnx = self._mysql_connection(options['server'], options['db'], options['user'], options['password'])
        
        # SiteSettings <- wp_options
        settings = self._fetch_site_settings(cnx)
        print "-> nice to meet you, "+settings.site.name
        
        # Users <- wp_users
        #TODO send users a reset password link instead
        users_count, wp_users_count = self._fetch_users(cnx)
        print "-> migrated {}/{} users".format(users_count, wp_users_count)
        print "-> all users should reset their passwords!"
        if self.wp_user_password :
            print "   default temporary password for all users: {}.".format(self.wp_user_password)
        else:
            print "   temporary user passwords default to their username."

        # Articles <- wp_posts
        wp_posts_a_count, articles_count = self._fetch_articles(cnx)
        print "-> migrated {} articles out of {} posts".format(articles_count, wp_posts_a_count)

        # StaticPages <- wp_posts
        wp_posts_p_count, pages_count = self._fetch_pages(cnx)
        print "-> migrated {} static pages out of {} posts".format(pages_count, wp_posts_p_count)    

        # Comments <- wp_comments
        comments_count = self._fetch_comments(cnx, settings.site)
        print "-> migrated {} comments".format(comments_count)

        # ExternalContent <- wp_links
        #TODO

        # Collections & Categories <- WP terms & term_taxonomies
        collection_counts, category_count, wp_term_taxonomy_count = self._fetch_term_taxonomies(cnx)
        print "-> migrated {} collections and {} categories out of {} term taxonomies".format(collection_counts, category_count, wp_term_taxonomy_count)

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
        CustomComment.objects.all().delete()
        User.objects.all().delete()
        Collection.objects.all().delete()
        Category.objects.all().delete()

    ########
    #QUERIES

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
        #see _clear_cyclope_db
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
        settings.show_author = 'USER' # WP uses users as authors
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
        fields = ('ID', 'post_title', 'post_status', 'post_date', 'post_modified', 'comment_status', 'post_content', 'post_excerpt', 'post_author')
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
        fields = ('ID', 'post_title','post_status','post_date', 'post_modified',  'comment_status', 'post_content', 'post_excerpt', 'post_author')
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
           instead of querying the related object for each comment and atomizing transactions, which could be expensive,
           we use an additional query for each content type only, and the transaction is repeated just as many times.
           we receive Site ID which is already above in the script."""
        fields = ('comment_ID', 'comment_author', 'comment_author_email', 'comment_author_url', 'comment_content', 'comment_date', 'comment_author_IP', 'comment_approved', 'comment_parent', 'user_id', 'comment_post_ID')
        post_types_with_comments = ('post', 'page')#TODO attachments
        counter = 0
        for post_type in post_types_with_comments:
            post_ids = self._post_type_ids(mysql_cnx, post_type)
            content_type = self._post_content_type(post_type)
            query = re.sub("[()']", '', "SELECT {} FROM ".format(fields))+self.wp_prefix+"comments WHERE comment_approved!='spam' AND comment_post_ID IN {}".format(post_ids)
            cursor = mysql_cnx.cursor()
            cursor.execute(query)
            #single transaction per content_type
            transaction.enter_transaction_management()
            transaction.managed(True)
            for wp_comment in cursor:
                comment_hash = dict(zip(fields,wp_comment))
                comment = self._wp_comment_to_custom(comment_hash, site, content_type)
                comment.save()
            transaction.commit()
            transaction.leave_transaction_management()
            counter += cursor.rowcount
            cursor.close()
        return counter

    def _fetch_users(self, mysql_cnx):
        """Populates cyclope django-based auth users from WP table wp_users."""
        fields = ('ID', 'user_login', 'user_nicename', 'display_name', 'user_email', 'user_registered')
        query = re.sub("[()']", '', "SELECT {} FROM ".format(fields))+self.wp_prefix+"users"
        cursor = mysql_cnx.cursor()
        cursor.execute(query)
        wp_users = cursor.fetchall()
        def _hash_result(fields, user): return dict(zip(fields,user))
        users = map(_hash_result,[fields]*len(wp_users), wp_users)
        users = map(self._wp_user_to_user, users)
        User.objects.bulk_create(users)
        counts = (User.objects.count(), cursor.rowcount)
        cursor.close()
        return counts

    def _fetch_term_taxonomies(self, mysql_cnx):
        """Brings wp_terms"""
        #Cyclope collections are WP term taxonomies
        query = "SELECT DISTINCT(taxonomy) FROM "+self.wp_prefix+"term_taxonomy"
        cursor = mysql_cnx.cursor()
        cursor.execute(query)
        for taxonomy in cursor :
            collection = self._wp_term_taxonomy_to_collection(taxonomy[0])
            collection.save()
        cursor.close()
        #Cyclope categories are WP terms
        cursor = mysql_cnx.cursor()
        fields = ('t.term_id', 't.name', 'tt.taxonomy', 'tt.parent', 'tt.description')#preserve'slug'? even for articles...
        query = re.sub("[()']", '', "SELECT {} FROM ".format(fields))+self.wp_prefix+"terms t INNER JOIN "+self.wp_prefix+"term_taxonomy tt ON t.term_id = tt.term_id"
        cursor.execute(query)
        #query for collection ids only once to associate them
        collection_ids = {}
        for collection in Collection.objects.all() :
            collection_ids[collection.name]=collection.id
        #save categorties in bulk so it doesn't call custom Category save, which doesn't allow custom ids (WP referential integrity)    
        categories=[]
        for term_taxonomy in cursor:
            cat_hash = dict(zip(fields, term_taxonomy))
            categories.append(self._wp_term_to_category(cat_hash,collection_ids))
        term_taxonomy_count = cursor.rowcount     
        cursor.close()
        Category.objects.bulk_create(categories)
        #Cyclope categorizations are WP term relationships
        object_type_ids = self._object_type_ids()#by this time posts are already created in our db
        fields = ('tr.object_id', 'tr.term_taxonomy_id', 'tt.term_id', 'tt.taxonomy', 'tr.term_order')
        query = re.sub("[()']", '', "SELECT {} FROM ".format(fields))+self.wp_prefix+"term_taxonomy tt INNER JOIN "+self.wp_prefix+"term_relationships tr ON tr.term_taxonomy_id=tt.term_taxonomy_id"
        cursor = mysql_cnx.cursor()
        cursor.execute(query)
        categorizations = []
        for term_relationship in cursor:
            categorizations.append(self._wp_term_relationship_to_categorization(dict(zip(fields, term_relationship)), object_type_ids))
        cursor.close()
        categorizations = filter(None, categorizations)#TODO links...
        Categorization.objects.bulk_create(categorizations)                
        #
        counts = (Collection.objects.count(), Category.objects.count(), term_taxonomy_count)
        return counts

    ########
    #HELPERS

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

    def _post_content_type(self, post_type):
        if post_type == 'post':
            return ContentType.objects.get(app_label="articles", model="article")
        elif post_type == 'page':
            return ContentType.objects.get(app_label="staticpages", model="staticpage")
        #elif post_type == 'attachment' TODO
        else:
            raise "Unexistent post type!"

    def _object_type_ids(self):
        #wp terms relate to posts, which are cyclope's articles, staticpages TODO or attachments
        #comming from the same tables, their IDs shouldn't intersect
        article_ids = []
        page_ids = []
        article_type_id = self._post_content_type('post').id
        page_type_id = self._post_content_type('page').id
        for article in Article.objects.all(): article_ids.append(article.id)
        for page in StaticPage.objects.all(): page_ids.append(page.id)
        return {article_type_id: article_ids, page_type_id: page_ids}
        #TODO terms can also relate to links?
    
    ###################
    #OBJECT CONVERSIONS
    
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
            #in WP all posts have a status, they are saved as the option that's set(?).
            #if the user then tries to close them all, he shouldn't set them one by one.
            #whe should set them to SITE default unless comments are explicitly closed, which is the minority(?)       
            allow_comments = 'SITE' if post['comment_status']!='closed' else 'NO',
            summary = post['post_excerpt'],
            #pretitle has no equivalent in WP
            #TODO #FKs: comments related_contents picture author source
            user_id = post['post_author'], # WP referential integrity maintained
            show_author = 'USER' #TODO default SITE doesn't work when site sets USER
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
            summary = post['post_excerpt'],
            #TODO related_contents comments
            user_id = post['post_author'], # WP referential integrity maintained
            show_author = 'USER' #TODO default SITE doesn't work when site sets USER
        )

    def _wp_comment_to_custom(self, comment, site, content_type):
        comment_parent = comment['comment_parent'] if comment['comment_parent']!=0 else None
        #tree_path and last_child_id are automagically set by threadedcomments framework
        return CustomComment(
            id = comment['comment_ID'],
            object_pk = comment['comment_post_ID'],
            content_type = content_type,
            site = site,
            user_name = comment['comment_author'],
            user_email = comment['comment_author_email'],
            user_url = comment['comment_author_url'],
            comment = comment['comment_content'],
            submit_date = comment['comment_date'],
            ip_address = comment['comment_author_IP'],
            ## WP referential integrity maintained, check why N's comments aren't all referenced
            user_id = comment['user_id'] if comment['user_id']!=0 else None,
            #TODO
            #is_public          comment_approved
            #is_removed         ..
            parent_id = comment_parent,
            subscribe = True #TODO Site default?
        )

    #https://docs.djangoproject.com/en/1.4/topics/auth/#fields
    def _wp_user_to_user(self, wp_user):
        user = User(
            id =  wp_user['ID'],
            username = wp_user['user_login'],
            first_name = wp_user['display_name'],
            #last_name=wp_user['user_nicename'], or parse display_name 
            #WP user_url will be lost
            email = wp_user['user_email'],
            is_staff=True,
            #user_status is a dead column in WP
            is_active=True,
            is_superuser=True,#else doesn't have any permissions
            #last_login='', we don't have this data in WP?
            date_joined = wp_user['user_registered']
        )
        password = self.wp_user_password if self.wp_user_password else user.username
        user.set_password(password)
        return user

    def _wp_term_taxonomy_to_collection(self, taxonomy):
        return Collection(
            name = taxonomy,#everything else to defaults
            #TODO check content_types, default_list_views, view_options
        )

    def _wp_term_to_category(self, term_taxonomy, collection_ids):
        return Category(
            id = term_taxonomy['t.term_id'],
            name = term_taxonomy['t.name'],
            collection_id = collection_ids[term_taxonomy['tt.taxonomy']],
            description = term_taxonomy['tt.description'],
            parent_id = term_taxonomy['tt.parent'] if term_taxonomy['tt.parent']!=0 else None,        
            #TODO hierarchical categories should properly set tree values
            #bulk creation fails if these are null
            lft=0,
            rght=0,
            tree_id=term_taxonomy['t.term_id'],
            level=0
        )

    def _wp_term_relationship_to_categorization(self, term_relationship, object_type_ids):
        def _get_object_type(object_type_ids, object_id):
            for item in object_type_ids.items(): 
                if object_id in item[1]:
                    return item[0]
        content_type_id = _get_object_type(object_type_ids, term_relationship['tr.object_id'])
        if content_type_id is None: return #TODO returning None for links, they will be treated in a next commit
        return Categorization(
            category_id = term_relationship['tt.term_id'],
            content_type_id = content_type_id,
            object_id = term_relationship['tr.object_id'],
            order = term_relationship['tr.term_order']
        )

