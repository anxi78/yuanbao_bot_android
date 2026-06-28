
// Fix Gradle 8.9+ implicit task dependency validation
// compileJavaWithJavac tasks must explicitly depend on AGP-generated tasks
afterEvaluate {
    tasks.configureEach { task ->
        if (task.name.matches('^compile(Debug|Release)JavaWithJavac$')) {
            def variant = (task.name =~ /(Debug|Release)/)[0][1]
            ["merge${variant}Assets",
             "compress${variant}Assets",
             "check${variant}DuplicateClasses",
             "desugar${variant}FileDependencies",
             "merge${variant}JavaResource",
             "merge${variant}Shaders"].each { dep ->
                def depTask = tasks.findByName(dep)
                if (depTask != null) {
                    task.dependsOn(depTask)
                }
            }
        }
    }
}
